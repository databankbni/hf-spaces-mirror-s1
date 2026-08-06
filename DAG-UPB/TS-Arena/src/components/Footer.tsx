'use client';

import Link from 'next/link';

interface FooterProps {
  /**
   * Absolute URL of the user console, or null if this instance has no
   * console. Resolved on the server in the root layout — see
   * `getConsoleUrl()`.
   */
  consoleUrl?: string | null;
}

export default function Footer({ consoleUrl = null }: FooterProps) {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="bg-white border-t border-gray-200 mt-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="flex flex-col sm:flex-row justify-between items-center space-y-4 sm:space-y-0">
          <div className="text-sm text-gray-500">
            © {currentYear} TS-Arena. All rights reserved.
          </div>
          <div className="flex flex-wrap justify-center gap-x-6 gap-y-2">
            {consoleUrl && (
              <a
                href={consoleUrl}
                className="text-sm text-gray-500 hover:text-gray-700 transition-colors"
              >
                Console
              </a>
            )}
            <Link
              href="/impressum"
              className="text-sm text-gray-500 hover:text-gray-700 transition-colors"
            >
              Impressum/Legal Notice
            </Link>
            <Link
              href="/datenschutz"
              className="text-sm text-gray-500 hover:text-gray-700 transition-colors"
            >
              Datenschutz/Privacy Policy
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
