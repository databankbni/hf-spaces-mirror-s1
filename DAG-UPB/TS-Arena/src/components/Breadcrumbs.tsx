'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronRight } from 'lucide-react';

interface BreadcrumbItem {
  label: string;
  href: string;
}

interface BreadcrumbsProps {
  items?: BreadcrumbItem[];
}

export default function Breadcrumbs({ items }: BreadcrumbsProps) {
  const pathname = usePathname();

  // Generate breadcrumbs from path if not provided
  const breadcrumbs = items || generateBreadcrumbsFromPath(pathname);

  if (breadcrumbs.length === 0) {
    return null;
  }

  return (
    <nav className="flex items-center space-x-2 text-sm text-gray-600 mb-6">
      <Link
        href="/"
        className="hover:text-gray-900 transition-colors"
      >
        Home
      </Link>
      {breadcrumbs.map((crumb, index) => (
        <div key={crumb.href} className="flex items-center space-x-2">
          <ChevronRight className="h-4 w-4 text-gray-400" />
          {index === breadcrumbs.length - 1 ? (
            <span className="font-medium text-gray-900">{crumb.label}</span>
          ) : (
            <Link
              href={crumb.href}
              className="hover:text-gray-900 transition-colors"
            >
              {crumb.label}
            </Link>
          )}
        </div>
      ))}
    </nav>
  );
}

function generateBreadcrumbsFromPath(pathname: string): BreadcrumbItem[] {
  const paths = pathname.split('/').filter(Boolean);
  const breadcrumbs: BreadcrumbItem[] = [];

  let currentPath = '';
  paths.forEach((path, index) => {
    currentPath += `/${path}`;
    
    // Create readable labels
    let label = path
      .split('-')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');

    // Special handling for specific routes
    if (path === 'challenges') {
      label = 'Challenges';
    } else if (path === 'add-model') {
      label = 'Add Model';
    } else if (!isNaN(Number(path))) {
      // If it's a number (ID), keep it as is
      label = `#${path}`;
    }

    breadcrumbs.push({
      label,
      href: currentPath,
    });
  });

  return breadcrumbs;
}
