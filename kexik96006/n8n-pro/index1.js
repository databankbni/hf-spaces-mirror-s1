const express = require('express');
const cors = require('cors');
const cron = require('node-cron');
const fetch = require('node-fetch');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT;

// Enable CORS
app.use(cors());

// Express JSON Parser with Safe Error Handling
app.use((req, res, next) => {
  express.json()(req, res, (err) => {
    if (err) {
      return res.status(400).json({ success: false, error: 'Invalid JSON body' });
    }
    next();
  });
});

// In-Memory Storage (7 Days Log History)
let pingLogs = [];
const MAX_LOG_AGE_MS = 7 * 24 * 60 * 60 * 1000;

// Ping Function
async function pingSupabase() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey =
    process.env.SUPABASE_ANON_KEY ||
    process.env.SUPABASE_PUBLISHABLE_KEY ||
    process.env.SUPABASE_SECRET_KEY;

  const timestamp = new Date().toISOString();

  if (!supabaseUrl) {
    const errorLog = {
      timestamp,
      status: 'FAILED',
      message: 'SUPABASE_URL is not defined in environment variables.',
    };
    addLog(errorLog);
    console.error(`[${timestamp}] Ping failed: SUPABASE_URL missing.`);
    return;
  }

  try {
    const cleanUrl = supabaseUrl.replace(/\/$/, '');

    // Method 1: Hit Supabase Auth Health Check Endpoint (Sab se reliable option)
    let response = await fetch(`${cleanUrl}/auth/v1/health`, {
      method: 'GET',
    });

    // Method 2: Fallback to REST API if Auth health is not available
    if (!response.ok && supabaseKey) {
      response = await fetch(`${cleanUrl}/rest/v1/`, {
        method: 'GET',
        headers: {
          'apikey': supabaseKey,
          'Authorization': `Bearer ${supabaseKey}`,
        },
      });
    }

    const isSuccess = response.status >= 200 && response.status < 300;

    const logEntry = {
      timestamp,
      status: isSuccess ? 'SUCCESS' : 'FAILED',
      statusCode: response.status,
      message: isSuccess
        ? 'Supabase responded successfully.'
        : `Ping failed with HTTP status ${response.status}`,
    };

    addLog(logEntry);
    console.log(`[${timestamp}] Ping executed. Status: ${response.status}`);
  } catch (error) {
    const errorLog = {
      timestamp,
      status: 'ERROR',
      statusCode: 500,
      message: error.message,
    };
    addLog(errorLog);
    console.error(`[${timestamp}] Ping error: ${error.message}`);
  }
}

// Memory Clean-up & Add Log Function
function addLog(newLog) {
  const now = Date.now();
  
  // Filter out logs older than 7 days
  pingLogs = pingLogs.filter((log) => {
    const logTime = new Date(log.timestamp).getTime();
    return now - logTime <= MAX_LOG_AGE_MS;
  });

  pingLogs.unshift(newLog);
}

// Cron Schedule: Every 12 hours
cron.schedule('0 */12 * * *', () => {
  console.log('Running scheduled Supabase ping...');
  pingSupabase();
});

// Immediate ping on server start
pingSupabase();

// API Endpoints
app.get('/api/status', (req, res) => {
  res.json({
    status: 'ONLINE',
    service: 'Supabase Keep-Alive Ping Service',
    totalLogsStored: pingLogs.length,
    lastPing: pingLogs[0] || null,
    retentionPolicy: '7 Days In-Memory Storage',
  });
});

app.get('/api/logs', (req, res) => {
  res.json({
    success: true,
    count: pingLogs.length,
    data: pingLogs,
  });
});

app.post('/api/ping-now', async (req, res) => {
  await pingSupabase();
  res.json({
    success: true,
    message: 'Manual ping triggered successfully.',
    latestLog: pingLogs[0],
  });
});

app.delete('/api/logs', (req, res) => {
  pingLogs = [];
  res.json({
    success: true,
    message: 'In-memory logs cleared successfully.',
  });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
  
});