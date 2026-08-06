import type { Metadata } from 'next';
import Link from 'next/link';

import Breadcrumbs from '@/src/components/Breadcrumbs';
import { formatPostDate, getAllPosts } from '@/src/content/news';

export const metadata: Metadata = {
  title: 'News — TS-Arena',
  description: 'Platform announcements: new challenges, model additions, and scoring changes.',
};

export default function NewsPage() {
  const posts = getAllPosts();

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Breadcrumbs items={[{ label: 'News', href: '/news' }]} />

        <h1 className="text-3xl font-bold text-gray-900 mb-2">News</h1>
        <p className="text-gray-600 mb-8">
          Platform announcements — new challenges, model additions, and changes to how
          forecasts are scored.
        </p>

        {posts.length === 0 ? (
          <div className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8">
            <p className="text-gray-600">No announcements yet.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {posts.map((post) => (
              <article
                key={post.slug}
                className="bg-white shadow-sm rounded-lg border border-gray-200 p-4 sm:p-6 hover:border-gray-300 transition-colors"
              >
                <time dateTime={post.date} className="text-sm text-gray-500">
                  {formatPostDate(post.date)}
                </time>
                <h2 className="mt-1 text-xl font-semibold text-gray-900">
                  <Link href={`/news/${post.slug}`} className="hover:text-blue-600 transition-colors">
                    {post.title}
                  </Link>
                </h2>
                {post.summary && (
                  <p className="mt-2 text-gray-700 leading-relaxed">{post.summary}</p>
                )}
                <Link
                  href={`/news/${post.slug}`}
                  className="mt-3 inline-block text-sm font-medium text-blue-600 hover:text-blue-800"
                >
                  Read more →
                </Link>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
