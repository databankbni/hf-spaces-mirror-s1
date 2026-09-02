/*
  ═══════════════════════════════════════════════════════════════
  KOMBAZ TRADING COMPANION — ESP32 physical alert device
  Polls /api/hardware/status on the KOMBAZ QUANT backend and drives
  an RGB LED (traffic light), a buzzer/vibration motor (edge-triggered
  alerts only), and an optional SSD1306 OLED (ticker / score / tail plan).

  Architecture:
    - Fully non-blocking (millis()-based state machine, no delay() in loop)
    - WiFi auto-reconnect with exponential backoff, self-heals without reboot
    - Remote config: poll interval / thresholds / watchlist pulled from
      /api/hardware/config at boot + refreshed periodically — retune from
      the server without reflashing firmware
    - Edge-triggered alerts: buzzer only fires on a light-state TRANSITION
      (e.g. green->red), never on every poll — avoids alert fatigue
    - TLS via WiFiClientSecure (setInsecure() for HF Spaces' cert chain;
      see NOTE below on pinning a certificate for production hardening)

  Hardware (adjust pins to your wiring):
    - Common-cathode RGB LED : 3x PWM-capable GPIO (see PIN_LED_*)
    - Buzzer or vibration motor (active-low or via transistor) : PIN_ALERT
    - Optional SSD1306 128x64 I2C OLED : SDA/SCL (define HAS_OLED below)
    - Optional pushbutton (manual refresh) : PIN_BUTTON, INPUT_PULLUP

  Libraries required (Arduino Library Manager):
    - ArduinoJson (v6.x)
    - Adafruit_SSD1306 + Adafruit_GFX   [only if HAS_OLED is 1]

  Board: ESP32 Dev Module (esp32 core, any variant with WiFi)
  ═══════════════════════════════════════════════════════════════
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include "secrets.h"   // WIFI_SSID, WIFI_PASSWORD, SERVER_HOST, DEVICE_KEY — see secrets_template.h

// ─── Feature flags ─────────────────────────────────────────────
#define HAS_OLED 0     // set to 1 if an SSD1306 OLED is wired up
#define HAS_BUTTON 1   // set to 0 if no manual-refresh button

#if HAS_OLED
  #include <Wire.h>
  #include <Adafruit_GFX.h>
  #include <Adafruit_SSD1306.h>
  #define OLED_W 128
  #define OLED_H 64
  Adafruit_SSD1306 display(OLED_W, OLED_H, &Wire, -1);
#endif

// ─── Pin map ───────────────────────────────────────────────────
const int PIN_LED_R   = 25;
const int PIN_LED_G   = 26;
const int PIN_LED_B   = 27;
const int PIN_ALERT   = 14;   // buzzer / vibration motor (through a transistor if >20mA)
const int PIN_BUTTON  = 4;    // manual refresh, active LOW (INPUT_PULLUP)
const int PIN_STATUS  = 2;    // onboard LED — blinks while connecting, solid when polling OK

// ─── PWM (LEDC) channels for the RGB LED ───────────────────────
const int CH_R = 0, CH_G = 1, CH_B = 2;
const int PWM_FREQ = 5000, PWM_RES = 8;   // 8-bit, 0-255

// ─── Runtime state ─────────────────────────────────────────────
enum LightState { LIGHT_UNKNOWN, LIGHT_GREEN, LIGHT_YELLOW, LIGHT_RED };
LightState currentLight = LIGHT_UNKNOWN;
LightState lastAlertedLight = LIGHT_UNKNOWN;

unsigned long lastStatusPoll   = 0;
unsigned long lastConfigPoll   = 0;
unsigned long pollIntervalMs   = 20000;   // overwritten by /api/hardware/config
unsigned long configRefreshMs  = 1800000; // 30 min default
String        watchlist        = "";      // from config; empty = server default

// WiFi backoff
unsigned long wifiRetryDelay   = 1000;
const unsigned long wifiRetryMax = 30000;
unsigned long lastWifiAttempt  = 0;

// Non-blocking status-LED blink (while connecting)
unsigned long lastBlink = 0;
bool blinkState = false;

// Non-blocking alert pattern
bool alertActive = false;
unsigned long alertStartedAt = 0;
int alertStep = 0;

// Last good payload, for OLED / debug
String lastTopTicker = "--";
float  lastTopScore  = 0;
int    lastTailShares = 0;
float  lastTailStop = 0, lastTailTarget = 0;

// ─── Forward declarations ──────────────────────────────────────
void connectWiFi();
void fetchConfig();
void fetchStatus();
void setLight(LightState s);
void driveAlert();
void updateOled();
String httpGetJson(const String& path);

// ═══════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[KOMBAZ] Trading Companion booting...");

  pinMode(PIN_STATUS, OUTPUT);
#if HAS_BUTTON
  pinMode(PIN_BUTTON, INPUT_PULLUP);
#endif
  pinMode(PIN_ALERT, OUTPUT);
  digitalWrite(PIN_ALERT, LOW);

  ledcSetup(CH_R, PWM_FREQ, PWM_RES); ledcAttachPin(PIN_LED_R, CH_R);
  ledcSetup(CH_G, PWM_FREQ, PWM_RES); ledcAttachPin(PIN_LED_G, CH_G);
  ledcSetup(CH_B, PWM_FREQ, PWM_RES); ledcAttachPin(PIN_LED_B, CH_B);
  setLight(LIGHT_UNKNOWN);   // dim blue-ish "booting" color

#if HAS_OLED
  Wire.begin();
  if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("KOMBAZ QUANT");
    display.println("connecting...");
    display.display();
  }
#endif

  connectWiFi();
  fetchConfig();     // pull poll interval / thresholds / watchlist
  fetchStatus();     // first status immediately, don't wait a full interval
  lastConfigPoll = lastStatusPoll = millis();
}

// ═══════════════════════════════════════════════════════════════
void loop() {
  unsigned long now = millis();

  // --- WiFi self-heal, non-blocking backoff ---
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(PIN_STATUS, (now / 300) % 2);  // fast blink = disconnected
    if (now - lastWifiAttempt > wifiRetryDelay) {
      lastWifiAttempt = now;
      connectWiFi();
      wifiRetryDelay = min(wifiRetryDelay * 2, wifiRetryMax);  // exponential backoff
    }
    driveAlert();
    return;  // skip polling until back online
  }
  wifiRetryDelay = 1000;  // reset backoff once connected
  digitalWrite(PIN_STATUS, HIGH);  // solid = connected

  // --- periodic config refresh ---
  if (now - lastConfigPoll >= configRefreshMs) {
    fetchConfig();
    lastConfigPoll = now;
  }

  // --- periodic status poll ---
  if (now - lastStatusPoll >= pollIntervalMs) {
    fetchStatus();
    lastStatusPoll = now;
  }

#if HAS_BUTTON
  // --- manual refresh button (debounced by simple edge check) ---
  static bool lastBtn = HIGH;
  bool btn = digitalRead(PIN_BUTTON);
  if (btn == LOW && lastBtn == HIGH) {
    Serial.println("[KOMBAZ] Manual refresh requested");
    fetchStatus();
    lastStatusPoll = now;
  }
  lastBtn = btn;
#endif

  driveAlert();
}

// ═══════════════════════════════════════════════════════════════
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("[WiFi] Connecting to %s...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) {
    digitalWrite(PIN_STATUS, (millis() / 150) % 2);
    delay(50);  // brief, bounded — only during initial connect attempt
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] Connected, IP=%s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("[WiFi] Attempt timed out, will retry with backoff");
  }
}

// ─── HTTP GET helper, returns response body or "" on failure ──
String httpGetJson(const String& path) {
  if (WiFi.status() != WL_CONNECTED) return "";
  WiFiClientSecure client;
  client.setInsecure();  // NOTE: for production, pin the HF Spaces cert instead
  HTTPClient https;
  String url = String("https://") + SERVER_HOST + path;
  if (!https.begin(client, url)) {
    Serial.println("[HTTP] begin() failed");
    return "";
  }
  https.addHeader("X-Device-Key", DEVICE_KEY);
  https.setTimeout(8000);
  int code = https.GET();
  String body = "";
  if (code == 200) {
    body = https.getString();
  } else {
    Serial.printf("[HTTP] GET %s -> %d\n", path.c_str(), code);
  }
  https.end();
  return body;
}

// ═══════════════════════════════════════════════════════════════
void fetchConfig() {
  String path = "/api/hardware/config";
  String body = httpGetJson(path);
  if (body.length() == 0) return;

  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    Serial.printf("[Config] JSON parse error: %s\n", err.c_str());
    return;
  }
  pollIntervalMs  = (unsigned long)doc["poll_interval_sec"].as<int>() * 1000UL;
  configRefreshMs = (unsigned long)doc["config_refresh_sec"].as<int>() * 1000UL;
  if (pollIntervalMs < 5000) pollIntervalMs = 5000;  // floor — be a polite client
  watchlist = doc["default_tickers"].as<String>();
  Serial.printf("[Config] poll=%lus refresh=%lus watchlist=%s\n",
                pollIntervalMs / 1000, configRefreshMs / 1000, watchlist.c_str());
}

// ═══════════════════════════════════════════════════════════════
void fetchStatus() {
  String path = "/api/hardware/status";
  if (watchlist.length() > 0) path += "?tickers=" + watchlist;
  String body = httpGetJson(path);
  if (body.length() == 0) return;

  // tail_plan (2 entries) + flags array — give the parser real headroom
  DynamicJsonDocument doc(2048);
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    Serial.printf("[Status] JSON parse error: %s\n", err.c_str());
    return;
  }

  const char* light = doc["light"] | "unknown";
  LightState newLight = LIGHT_UNKNOWN;
  if      (strcmp(light, "green")  == 0) newLight = LIGHT_GREEN;
  else if (strcmp(light, "yellow") == 0) newLight = LIGHT_YELLOW;
  else if (strcmp(light, "red")    == 0) newLight = LIGHT_RED;

  lastTopTicker = doc["top_ticker"].as<String>();
  lastTopScore  = doc["top_score"].as<float>();
  if (doc["tail_plan"][0].is<JsonObject>()) {
    lastTailShares = doc["tail_plan"][0]["shares"].as<int>();
    lastTailStop   = doc["tail_plan"][0]["stop"].as<float>();
    lastTailTarget = doc["tail_plan"][0]["target"].as<float>();
  }

  Serial.printf("[Status] light=%s top=%s(%.1f) shares=%d cached=%s\n",
                light, lastTopTicker.c_str(), lastTopScore, lastTailShares,
                (doc["cached"] | false) ? "yes" : "no");

  setLight(newLight);

  // Edge-triggered alert: only buzz on an actual state change to RED,
  // or on any change once we've left UNKNOWN — never on every poll.
  if (newLight != currentLight && newLight != LIGHT_UNKNOWN) {
    bool worseningToRed = (newLight == LIGHT_RED && lastAlertedLight != LIGHT_RED);
    if (worseningToRed) {
      alertActive = true;
      alertStartedAt = millis();
      alertStep = 0;
      lastAlertedLight = newLight;
    }
  }
  currentLight = newLight;
  updateOled();
}

// ─── RGB LED color per state (values are 0-255 per channel) ───
void setLight(LightState s) {
  switch (s) {
    case LIGHT_GREEN:  ledcWrite(CH_R, 0);   ledcWrite(CH_G, 200); ledcWrite(CH_B, 0);   break;
    case LIGHT_YELLOW: ledcWrite(CH_R, 200); ledcWrite(CH_G, 140); ledcWrite(CH_B, 0);   break;
    case LIGHT_RED:     ledcWrite(CH_R, 220); ledcWrite(CH_G, 0);  ledcWrite(CH_B, 0);   break;
    default:            ledcWrite(CH_R, 0);   ledcWrite(CH_G, 0);  ledcWrite(CH_B, 60);  break; // booting/unknown = dim blue
  }
}

// ─── Non-blocking alert pattern: 3 short pulses, then done ─────
void driveAlert() {
  if (!alertActive) return;
  unsigned long elapsed = millis() - alertStartedAt;
  const unsigned long PULSE_ON = 150, PULSE_OFF = 150;
  unsigned long cycle = PULSE_ON + PULSE_OFF;
  int maxPulses = 3;

  if (alertStep >= maxPulses) {
    digitalWrite(PIN_ALERT, LOW);
    alertActive = false;
    return;
  }
  unsigned long inCycle = elapsed % cycle;
  digitalWrite(PIN_ALERT, inCycle < PULSE_ON ? HIGH : LOW);
  alertStep = elapsed / cycle;
}

// ─── OLED refresh (no-op if HAS_OLED is 0) ─────────────────────
void updateOled() {
#if HAS_OLED
  display.clearDisplay();
  display.setCursor(0, 0);
  display.setTextSize(1);
  display.println("KOMBAZ // TAIL 1050");
  display.setTextSize(2);
  display.setCursor(0, 14);
  display.println(lastTopTicker);
  display.setTextSize(1);
  display.setCursor(0, 34);
  display.printf("Score: %.1f\n", lastTopScore);
  display.printf("Sh:%d Stop:%.2f\n", lastTailShares, lastTailStop);
  display.printf("Target: %.2f\n", lastTailTarget);
  display.display();
#endif
}

