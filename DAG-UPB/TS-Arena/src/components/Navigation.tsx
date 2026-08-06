'use client';

import { Disclosure, DisclosureButton, DisclosurePanel } from '@headlessui/react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { siGithub } from 'simple-icons/icons';

interface NavigationProps {
  /**
   * Whether this instance has any news posts. Resolved on the server in the
   * root layout — posts come from an external content repo that a fork may
   * not have, and an empty "News" tab is worse than no tab.
   */
  showNews?: boolean;
  /**
   * Absolute URL of the user console, or null if this instance has no
   * console. Also resolved in the root layout — see `getConsoleUrl()`.
   */
  consoleUrl?: string | null;
}

interface NavItem {
  href: string;
  label: string;
  /** Renders a plain <a> and never matches the active state — the console
      lives on another domain, so next/link and pathname do not apply. */
  external?: boolean;
}

export default function Navigation({ showNews = false, consoleUrl = null }: NavigationProps) {
  const pathname = usePathname();

  const navItems: NavItem[] = [
    { href: '/', label: 'Rankings' },
    { href: '/challenges', label: 'Challenges' },
    { href: '/add-model', label: 'Add Model' },
    { href: '/backtesting-archive', label: 'Backtesting Archive' },
    ...(showNews ? [{ href: '/news', label: 'News' }] : []),
    { href: '/about', label: 'About' },
    ...(consoleUrl ? [{ href: consoleUrl, label: 'Console', external: true }] : []),
  ];

  return (
    <Disclosure as="nav" className="bg-white shadow-sm border-b border-gray-200">
      {({ open }) => (
        <>
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between h-16">
              <div className="flex">
                <div className="flex-shrink-0 flex items-center">
                  <Link href="/" className="text-xl font-bold text-gray-900 hover:text-blue-600 transition-colors cursor-pointer">
                    TS-Arena
                  </Link>
                </div>
                <div className="hidden lg:ml-6 lg:flex lg:space-x-8">
                  {navItems.map((item) => {
                    const baseClasses = 'inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium transition-colors';
                    const inactiveClasses = 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700';

                    if (item.external) {
                      return (
                        <a key={item.href} href={item.href} className={`${baseClasses} ${inactiveClasses}`}>
                          {item.label}
                        </a>
                      );
                    }

                    const isActive = pathname === item.href;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={`${baseClasses} ${
                          isActive ? 'border-blue-500 text-gray-900' : inactiveClasses
                        }`}
                      >
                        {item.label}
                      </Link>
                    );
                  })}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <a
                  href="https://github.com/DAG-UPB/ts-arena"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                  aria-label="View on GitHub"
                >
                  <svg role="img" viewBox="0 0 24 24" className="w-5 h-5 fill-current" xmlns="http://www.w3.org/2000/svg">
                    <path d={siGithub.path} />
                  </svg>
                  <span>GitHub</span>
                </a>
                <DisclosureButton className="lg:hidden inline-flex items-center justify-center h-11 w-11 -mr-1 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
                  <span className="sr-only">{open ? 'Close main menu' : 'Open main menu'}</span>
                  {open ? (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className="w-6 h-6" aria-hidden="true">
                      <path d="M6 6l12 12M18 6L6 18" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className="w-6 h-6" aria-hidden="true">
                      <path d="M4 7h16M4 12h16M4 17h16" />
                    </svg>
                  )}
                </DisclosureButton>
              </div>
            </div>
          </div>

          <DisclosurePanel className="lg:hidden border-t border-gray-200">
            {({ close }) => (
              <div className="py-2">
                {navItems.map((item) => {
                  const baseClasses = 'flex items-center min-h-[44px] py-2 pl-3 pr-4 border-l-4 text-base font-medium transition-colors';
                  const inactiveClasses = 'border-transparent text-gray-500 hover:border-gray-300 hover:bg-gray-50 hover:text-gray-700';

                  if (item.external) {
                    return (
                      <a
                        key={item.href}
                        href={item.href}
                        onClick={() => close()}
                        className={`${baseClasses} ${inactiveClasses}`}
                      >
                        {item.label}
                      </a>
                    );
                  }

                  const isActive = pathname === item.href;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => close()}
                      aria-current={isActive ? 'page' : undefined}
                      className={`${baseClasses} ${
                        isActive ? 'border-blue-500 bg-blue-50 text-gray-900' : inactiveClasses
                      }`}
                    >
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            )}
          </DisclosurePanel>
        </>
      )}
    </Disclosure>
  );
}
