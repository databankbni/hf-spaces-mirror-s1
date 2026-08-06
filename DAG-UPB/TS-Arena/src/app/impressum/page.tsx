'use client';

import Breadcrumbs from '@/src/components/Breadcrumbs';

export default function ImpressumPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Breadcrumbs
          items={[
            { label: 'Impressum/Legal Notice', href: '/impressum' },
          ]}
        />
        <div className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8">
          {/* German Version */}
          <h1 className="text-3xl font-bold text-gray-900 mb-6">Impressum</h1>
          
          <div className="space-y-6 text-gray-700">
            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Verantwortlich für den Inhalt</h2>
              <div className="flex flex-col sm:flex-row gap-6 items-start justify-between">
                <p>
                  Prof. Dr. Oliver Müller <br />
                  Data Analytics Group<br />
                  Universität Paderborn<br />
                  Warburger Str. 100<br />
                  33098 Paderborn<br />
                  Deutschland
                </p>
                <div className="flex-shrink-0 sm:ml-auto">
                  <a 
                    href="https://go.upb.de/data-analytics" 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="inline-block hover:opacity-80 transition-opacity"
                  >
                    <img 
                      src="/data_analytics_group.png" 
                      alt="Data Analytics Group" 
                      className="h-20 w-auto"
                    />
                  </a>
                </div>
              </div>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Kontakt</h2>
              <p>
                E-Mail: <a href="mailto:DataAnalytics@wiwi.uni-paderborn.de" className="text-blue-600 hover:text-blue-800 underline">DataAnalytics@wiwi.uni-paderborn.de</a><br />
                Website: <a href="https://go.upb.de/data-analytics" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-800 underline">https://go.upb.de/data-analytics</a>
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Urheberrechtshinweis</h2>
              <p className="leading-relaxed">
                Die Urheber- und Nutzungsrechte (Copyright) für Texte, Grafiken, Bilder, Design und Quellcode liegen soweit nicht anders angegeben bei der Universität Paderborn. Die Erstellung, Verwendung und Weitergabe von Kopien in elektronischer oder ausgedruckter Form bedarf der Genehmigung.
              </p>
            </section>

            <section>
              <h2 className="text-xl font-semibold text-gray-900 mb-3">Haftungshinweis</h2>
              <p className="leading-relaxed">
                Für auf den Seiten vorhandene externe Links und die darüber verfügbaren Inhalte übernehmen wir keine Haftung. Sie stellen kein Angebot der Universität Paderborn dar. Für den Inhalt der verlinkten Seiten sind ausschließlich deren Betreiber verantwortlich.
              </p>
            </section>
          </div>

          {/* English Version */}
          <div className="mt-12 pt-8 border-t border-gray-300">
            <h1 className="text-3xl font-bold text-gray-900 mb-6">Legal Notice</h1>
            
            <div className="space-y-6 text-gray-700">
              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Responsible for Content</h2>
                <div className="flex flex-col sm:flex-row gap-6 items-start justify-between">
                  <p>
                    Prof. Dr. Oliver Müller <br />
                    Data Analytics Group<br />
                    Universität Paderborn<br />
                    Warburger Str. 100<br />
                    33098 Paderborn<br />
                    Germany
                  </p>
                  <div className="flex-shrink-0 sm:ml-auto">
                    <a 
                      href="https://go.upb.de/data-analytics" 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="inline-block hover:opacity-80 transition-opacity"
                    >
                      <img 
                        src="/data_analytics_group.png" 
                        alt="Data Analytics Group" 
                        className="h-20 w-auto"
                      />
                    </a>
                  </div>
                </div>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Contact</h2>
                <p>
                  Email: <a href="mailto:DataAnalytics@wiwi.uni-paderborn.de" className="text-blue-600 hover:text-blue-800 underline">DataAnalytics@wiwi.uni-paderborn.de</a><br />
                  Website: <a href="https://go.upb.de/data-analytics" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-800 underline">https://go.upb.de/data-analytics</a>
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Copyright Notice</h2>
                <p className="leading-relaxed">
                  The copyright and usage rights for texts, graphics, images, design and source code lie, unless otherwise stated, 
                  with Paderborn University. The creation, use and distribution of copies in electronic or printed form requires permission.
                </p>
              </section>

              <section>
                <h2 className="text-xl font-semibold text-gray-900 mb-3">Liability Notice</h2>
                <p className="leading-relaxed">
                  We assume no liability for external links on the pages and the content available via them. 
                  They do not constitute an offer from Paderborn University. The operators of the linked pages are solely responsible 
                  for their content.
                </p>
              </section>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
