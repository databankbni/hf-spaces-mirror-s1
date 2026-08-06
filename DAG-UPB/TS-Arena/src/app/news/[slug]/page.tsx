import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';

import Breadcrumbs from '@/src/components/Breadcrumbs';
import { findPost, formatPostDate, getAllPosts } from '@/src/content/news';

interface PageProps {
  params: Promise<{ slug: string }>;
}

export function generateStaticParams() {
  return getAllPosts().map((post) => ({ slug: post.slug }));
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const post = findPost(slug);
  if (!post) return { title: 'News — TS-Arena' };

  return {
    title: `${post.title} — TS-Arena`,
    description: post.summary,
  };
}

export default async function NewsPostPage({ params }: PageProps) {
  const { slug } = await params;
  const post = findPost(slug);

  if (!post) {
    notFound();
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Breadcrumbs
          items={[
            { label: 'News', href: '/news' },
            { label: post.title, href: `/news/${post.slug}` },
          ]}
        />

        <article className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8">
          <time dateTime={post.date} className="text-sm text-gray-500">
            {formatPostDate(post.date)}
          </time>
          <h1 className="mt-1 text-3xl font-bold text-gray-900">{post.title}</h1>
          {post.author && <p className="mt-2 text-sm text-gray-600">By {post.author}</p>}

          <div
            className="news-body mt-6 text-gray-700"
            dangerouslySetInnerHTML={{ __html: post.html }}
          />
        </article>

        <Link
          href="/news"
          className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-blue-600 hover:text-blue-800"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to news
        </Link>
      </div>
    </div>
  );
}
