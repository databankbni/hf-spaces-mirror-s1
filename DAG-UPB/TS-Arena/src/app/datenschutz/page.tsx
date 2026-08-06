'use client';

import Breadcrumbs from '@/src/components/Breadcrumbs';

export default function DatenschutzPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Breadcrumbs
          items={[
            { label: 'Datenschutz/Privacy Policy', href: '/datenschutz' },
          ]}
        />
        <div className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8">
          {/* German Version */}
          <h1 className="text-3xl font-bold text-gray-900 mb-6">Datenschutzerklärung</h1>

          <div className="space-y-6 text-gray-700">
            <p className="leading-relaxed">
              Der Schutz Ihrer personenbezogenen Daten ist uns wichtig. Nachfolgend informieren wir Sie
              darüber, welche Daten beim Besuch dieser Website verarbeitet werden, zu welchem Zweck und
              auf welcher Rechtsgrundlage das geschieht. TS-Arena verwendet <strong>keine Cookies</strong>{' '}
              und speichert keine Informationen auf Ihrem Endgerät.
            </p>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Verantwortlicher</h2>
              <p>
                Universität Paderborn<br />
                Warburger Str. 100<br />
                33098 Paderborn<br />
                Deutschland
              </p>
              <p className="mt-3">
                Inhaltlich verantwortlich für diese Website:<br />
                Prof. Dr. Oliver Müller, Data Analytics Group<br />
                E-Mail: <a href="mailto:DataAnalytics@wiwi.uni-paderborn.de" className="text-blue-600 hover:text-blue-800 underline">DataAnalytics@wiwi.uni-paderborn.de</a>
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Datenschutzbeauftragter</h2>
              <p>
                Datenschutzbeauftragter der Universität Paderborn<br />
                Warburger Str. 100, 33098 Paderborn<br />
                E-Mail: <a href="mailto:datenschutz@uni-paderborn.de" className="text-blue-600 hover:text-blue-800 underline">datenschutz@uni-paderborn.de</a><br />
                Telefon: +49 5251 60-4444
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Aufruf der Website</h2>
              <p className="leading-relaxed">
                Um Ihnen diese Website ausliefern zu können, muss Ihre IP-Adresse technisch bedingt an
                unseren Server übermittelt werden. Sie wird ausschließlich für die Dauer der Auslieferung
                verarbeitet. <strong>Es werden keine Zugriffsprotokolle mit IP-Adressen von Besucherinnen und
                Besuchern geführt:</strong> der Zugriffslog des vorgelagerten Webservers ist deaktiviert, die
                Anwendungsserver protokollieren lediglich die interne Adresse des vorgelagerten Dienstes,
                und die Website selbst protokolliert keine Seitenaufrufe.
              </p>
              <p className="leading-relaxed mt-3">
                Rechtsgrundlage ist Art. 6 Abs. 1 lit. f DSGVO. Unser berechtigtes Interesse liegt in der
                technisch fehlerfreien Bereitstellung der Website.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Reichweitenmessung mit Umami</h2>
              <p className="leading-relaxed">
                Wir nutzen <strong>Umami</strong>, eine selbst betriebene Software zur Reichweitenmessung.
                Umami läuft auf Servern der Universität Paderborn. Es werden keine Daten an Dritte
                übermittelt und keine Daten in Drittländer übertragen. Umami setzt <strong>keine
                Cookies</strong> und speichert keine Informationen auf Ihrem Endgerät. Eine
                websiteübergreifende Verfolgung findet nicht statt.
              </p>

              <p className="leading-relaxed mt-3">Bei einem Seitenaufruf werden folgende Daten gespeichert:</p>
              <ul className="list-disc list-inside space-y-1 mt-2 ml-2">
                <li>aufgerufene Seite (Pfad), Seitentitel und Hostname</li>
                <li>die zuvor besuchte Seite (Referrer), sofern übermittelt</li>
                <li>Zeitpunkt des Aufrufs</li>
                <li>Bildschirmgröße, Spracheinstellung des Browsers</li>
                <li>Browser, Betriebssystem und Gerätetyp</li>
                <li>ungefährer Standort, abgeleitet aus der IP-Adresse (Land, Region und Stadt)</li>
                <li>eine pseudonyme Besucher- und Sitzungskennung (siehe unten)</li>
              </ul>

              <p className="leading-relaxed mt-3">
                <strong>Umgang mit der IP-Adresse:</strong> Ihre IP-Adresse wird beim Empfang eines
                Seitenaufrufs für zwei Zwecke verarbeitet: zur Ableitung des ungefähren Standorts und zur
                Bildung der pseudonymen Besucherkennung. Danach wird sie verworfen. <strong>Die IP-Adresse
                wird nicht in der Datenbank gespeichert</strong> und ist aus den gespeicherten Daten nicht
                rekonstruierbar. Die Besucherkennung wird monatlich neu gebildet; danach lassen sich frühere
                und spätere Besuche derselben Person nicht mehr miteinander verknüpfen.
              </p>
              <p className="leading-relaxed mt-3">
                <strong>Zweck</strong> ist die statistische Auswertung der Nutzung, um zu verstehen, welche
                Inhalte genutzt werden und in welchen Regionen die Plattform eingesetzt wird, und um die
                Website darauf aufbauend zu verbessern. <strong>Rechtsgrundlage</strong> ist Art. 6 Abs. 1 lit. f DSGVO;
                unser berechtigtes Interesse liegt in der bedarfsgerechten Gestaltung dieser Website. Eine
                Profilbildung oder eine Zusammenführung mit anderen Datenquellen findet nicht statt.
              </p>
              <p className="leading-relaxed mt-3">
                <strong>Speicherdauer:</strong> Die oben genannten Einzeldaten werden nach{' '}
                <strong>12 Monaten</strong> gelöscht. Vor der Löschung werden daraus monatliche
                Summenstatistiken gebildet (zum Beispiel Anzahl der Seitenaufrufe je Monat und Land). Diese
                Statistiken enthalten ausschließlich Zählwerte ohne Personenbezug und werden dauerhaft
                aufbewahrt.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Newsbereich</h2>
              <p className="leading-relaxed">
                Die Beiträge im Newsbereich sind statische Texte, die bei der Erstellung der Website fest
                eingebunden werden. Es gibt keine Kommentarfunktion, keine Anmeldung und keinen Newsletter.
                Beim Lesen eines Beitrags werden keine anderen Daten verarbeitet als beim Aufruf jeder
                anderen Seite dieser Website.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Teilnahme am Benchmark</h2>
              <p className="leading-relaxed">
                Diese Website enthält keine Formulare. Wer mit einem eigenen Modell am Benchmark teilnehmen
                möchte, tut dies über unser API-Portal beziehungsweise über die im Bereich „Add Model“
                genannten Wege. Dabei verarbeiten wir die von Ihnen angegebenen Daten: Benutzername,
                E-Mail-Adresse und Organisation sowie einen technischen Zugriffsschlüssel.
              </p>
              <p className="leading-relaxed mt-3">
                Diese Daten dienen ausschließlich der Durchführung des Benchmarks. Modellname und
                Ergebnisse werden auf der Rangliste veröffentlicht; Ihre E-Mail-Adresse wird nicht
                veröffentlicht. Rechtsgrundlage ist Art. 6 Abs. 1 lit. b DSGVO. Die Daten werden gespeichert,
                solange Sie am Benchmark teilnehmen.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Externe Inhalte und Links</h2>
              <p className="leading-relaxed">
                Diese Website bindet keine Inhalte von fremden Servern ein. Insbesondere werden Schriftarten
                lokal ausgeliefert, es besteht also keine Verbindung zu externen Schriftarten-Diensten.
                Links auf externe Seiten (etwa GitHub oder arXiv) sind als solche erkennbar; für deren
                Datenverarbeitung sind ausschließlich die jeweiligen Anbieter verantwortlich.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Ihre Rechte</h2>
              <p className="leading-relaxed">
                Sie haben das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16 DSGVO), Löschung
                (Art. 17 DSGVO), Einschränkung der Verarbeitung (Art. 18 DSGVO) und Datenübertragbarkeit
                (Art. 20 DSGVO).
              </p>
              <p className="leading-relaxed mt-3">
                <strong>Widerspruchsrecht (Art. 21 DSGVO):</strong> Soweit wir Daten auf Grundlage
                berechtigter Interessen verarbeiten, können Sie dieser Verarbeitung aus Gründen, die sich aus
                Ihrer besonderen Situation ergeben, jederzeit widersprechen. Wenden Sie sich dazu an die oben
                genannten Kontaktadressen. Die Reichweitenmessung können Sie zusätzlich unterbinden, indem
                Sie die Ausführung des Analyse-Skripts in Ihrem Browser blockieren, etwa über eine
                entsprechende Browsererweiterung.
              </p>
              <p className="leading-relaxed mt-3">
                Unabhängig davon steht Ihnen ein Beschwerderecht bei einer Aufsichtsbehörde zu, für uns
                zuständig ist die Landesbeauftragte für Datenschutz und Informationsfreiheit
                Nordrhein-Westfalen, Kavalleriestr. 2-4, 40213 Düsseldorf.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Änderungen dieser Erklärung</h2>
              <p className="leading-relaxed">
                Wir passen diese Datenschutzerklärung an, wenn sich die zugrunde liegende Verarbeitung
                ändert. Es gilt die jeweils auf dieser Seite veröffentlichte Fassung.
              </p>
            </section>
          </div>

          {/* English Version */}
          <div className="mt-12 pt-8 border-t border-gray-300">
            <h1 className="text-3xl font-bold text-gray-900 mb-6">Privacy Policy</h1>

            <div className="space-y-6 text-gray-700">
              <p className="leading-relaxed">
                Protecting your personal data matters to us. Below we explain which data is processed when
                you visit this website, for what purpose, and on what legal basis. TS-Arena uses{' '}
                <strong>no cookies</strong> and stores no information on your device. In case of doubt, the
                German version above prevails.
              </p>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Controller</h2>
                <p>
                  Paderborn University<br />
                  Warburger Str. 100<br />
                  33098 Paderborn<br />
                  Germany
                </p>
                <p className="mt-3">
                  Responsible for the content of this website:<br />
                  Prof. Dr. Oliver Müller, Data Analytics Group<br />
                  Email: <a href="mailto:DataAnalytics@wiwi.uni-paderborn.de" className="text-blue-600 hover:text-blue-800 underline">DataAnalytics@wiwi.uni-paderborn.de</a>
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Data Protection Officer</h2>
                <p>
                  Data Protection Officer of Paderborn University<br />
                  Warburger Str. 100, 33098 Paderborn, Germany<br />
                  Email: <a href="mailto:datenschutz@uni-paderborn.de" className="text-blue-600 hover:text-blue-800 underline">datenschutz@uni-paderborn.de</a><br />
                  Phone: +49 5251 60-4444
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Visiting the website</h2>
                <p className="leading-relaxed">
                  To deliver this website to you, your IP address has to be transmitted to our server for
                  technical reasons. It is processed only for as long as the response takes.{' '}
                  <strong>No access logs containing visitor IP addresses are kept:</strong> the access log of
                  the upstream web server is disabled, the application servers only record the internal
                  address of the upstream service, and the website itself does not log page requests.
                </p>
                <p className="leading-relaxed mt-3">
                  The legal basis is Art. 6(1)(f) GDPR. Our legitimate interest is the technically correct
                  delivery of the website.
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Analytics with Umami</h2>
                <p className="leading-relaxed">
                  We use <strong>Umami</strong>, a self-hosted analytics tool. Umami runs on servers of
                  Paderborn University. No data is passed to third parties and no data is transferred to
                  third countries. Umami sets <strong>no cookies</strong> and stores no information on your
                  device. No cross-site tracking takes place.
                </p>

                <p className="leading-relaxed mt-3">The following data is stored per page view:</p>
                <ul className="list-disc list-inside space-y-1 mt-2 ml-2">
                  <li>the page visited (path), page title and hostname</li>
                  <li>the previously visited page (referrer), if transmitted</li>
                  <li>the time of the visit</li>
                  <li>screen size and browser language</li>
                  <li>browser, operating system and device type</li>
                  <li>approximate location derived from the IP address (country, region and city)</li>
                  <li>a pseudonymous visitor and session identifier (see below)</li>
                </ul>

                <p className="leading-relaxed mt-3">
                  <strong>How your IP address is handled:</strong> on receipt of a page view your IP address
                  is processed for two purposes: to derive the approximate location, and to form the
                  pseudonymous visitor identifier. It is then discarded. <strong>The IP address is never
                  written to the database</strong> and cannot be reconstructed from the stored data. The
                  visitor identifier is formed anew each month; after that, earlier and later visits by the
                  same person can no longer be linked.
                </p>
                <p className="leading-relaxed mt-3">
                  The <strong>purpose</strong> is statistical analysis of usage, to understand which content
                  is used and in which regions the platform is used, and to improve the website accordingly. The{' '}
                  <strong>legal basis</strong> is Art. 6(1)(f) GDPR; our legitimate interest is designing
                  this website to meet actual demand. No profiling takes place and the data is not combined
                  with other sources.
                </p>
                <p className="leading-relaxed mt-3">
                  <strong>Retention:</strong> the individual records above are deleted after{' '}
                  <strong>12 months</strong>. Before deletion they are condensed into monthly totals (for
                  example the number of page views per month and country). Those statistics contain only
                  counts without any personal reference and are kept indefinitely.
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">News section</h2>
                <p className="leading-relaxed">
                  News posts are static texts built into the website. There is no comment function, no sign-up
                  and no newsletter. Reading a post processes no data beyond what any other page of this
                  website processes.
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Participating in the benchmark</h2>
                <p className="leading-relaxed">
                  This website contains no forms. To enter your own model into the benchmark you use our API
                  portal or the routes described under &ldquo;Add Model&rdquo;. In doing so we process the data you
                  provide: user name, email address and organisation, together with a technical access key.
                </p>
                <p className="leading-relaxed mt-3">
                  This data is used solely to operate the benchmark. Model names and results are published on
                  the leaderboard; your email address is not published. The legal basis is Art. 6(1)(b) GDPR.
                  The data is stored for as long as you take part in the benchmark.
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">External content and links</h2>
                <p className="leading-relaxed">
                  This website embeds no content from external servers. In particular, fonts are served
                  locally, so no connection to an external font service is made. Links to external sites
                  (such as GitHub or arXiv) are recognisable as such; their operators alone are responsible
                  for the data processing that happens there.
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Your rights</h2>
                <p className="leading-relaxed">
                  You have the right of access (Art. 15 GDPR), rectification (Art. 16 GDPR), erasure
                  (Art. 17 GDPR), restriction of processing (Art. 18 GDPR) and data portability
                  (Art. 20 GDPR).
                </p>
                <p className="leading-relaxed mt-3">
                  <strong>Right to object (Art. 21 GDPR):</strong> where we process data on the basis of
                  legitimate interests, you may object at any time on grounds relating to your particular
                  situation, using the contact details above. You can additionally prevent analytics by
                  blocking the analytics script in your browser, for example with a browser extension.
                </p>
                <p className="leading-relaxed mt-3">
                  You also have the right to lodge a complaint with a supervisory authority. The authority
                  responsible for us is the State Commissioner for Data Protection and Freedom of Information
                  North Rhine-Westphalia, Kavalleriestr. 2-4, 40213 Düsseldorf, Germany.
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Changes to this policy</h2>
                <p className="leading-relaxed">
                  We update this privacy policy when the underlying processing changes. The version published
                  on this page is the one that applies.
                </p>
              </section>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
