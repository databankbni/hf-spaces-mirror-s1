-- CreateTable
CREATE TABLE "Account" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "provider" TEXT NOT NULL,
    "providerAccountId" TEXT NOT NULL,
    "refresh_token" TEXT,
    "access_token" TEXT,
    "expires_at" INTEGER,
    "token_type" TEXT,
    "scope" TEXT,
    "id_token" TEXT,
    "session_state" TEXT,

    CONSTRAINT "Account_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Session" (
    "id" TEXT NOT NULL,
    "sessionToken" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "expires" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "VerificationToken" (
    "identifier" TEXT NOT NULL,
    "token" TEXT NOT NULL,
    "expires" TIMESTAMP(3) NOT NULL
);

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "password_hash" TEXT,
    "name" TEXT,
    "role" TEXT NOT NULL DEFAULT 'user',
    "emailVerified" TIMESTAMP(3),
    "image" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Book" (
    "id" TEXT NOT NULL,
    "source_url" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "title_vi" TEXT NOT NULL,
    "title_en" TEXT,
    "author_vi" TEXT,
    "description_vi" TEXT,
    "status" TEXT,
    "cover_url" TEXT,
    "chapters_count" INTEGER NOT NULL DEFAULT 0,
    "views_count" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Book_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Chapter" (
    "id" TEXT NOT NULL,
    "book_source_url" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "title_vi" TEXT,
    "url" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "chapter_no" INTEGER NOT NULL,
    "access" TEXT,
    "content" TEXT,
    "is_story_content" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Chapter_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CrawlJob" (
    "id" TEXT NOT NULL,
    "job_id" TEXT NOT NULL,
    "book_url" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "total_chapters" INTEGER NOT NULL DEFAULT 0,
    "crawled_chapters" INTEGER NOT NULL DEFAULT 0,
    "current_chapter_index" INTEGER NOT NULL DEFAULT 0,
    "current_chapter_title" TEXT,
    "current_chapter_url" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "bookId" TEXT NOT NULL,

    CONSTRAINT "CrawlJob_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Video" (
    "id" TEXT NOT NULL,
    "book_url" TEXT NOT NULL,
    "video_url" TEXT NOT NULL,
    "chapter_start" INTEGER NOT NULL,
    "chapter_count" INTEGER NOT NULL,
    "voice" TEXT NOT NULL,
    "rate" TEXT NOT NULL,
    "job_id" TEXT NOT NULL,
    "bookId" TEXT,
    "thumbnail_url" TEXT,
    "book_title" TEXT,
    "author_name" TEXT,
    "video_title" TEXT,
    "video_description" TEXT,
    "video_tags" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Video_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ReadingHistory" (
    "id" TEXT NOT NULL,
    "userEmail" TEXT NOT NULL,
    "book_url" TEXT NOT NULL,
    "chapter_slug" TEXT NOT NULL,
    "chapter_title" TEXT NOT NULL,
    "chapter_url" TEXT,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ReadingHistory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "UserLibrary" (
    "id" TEXT NOT NULL,
    "userEmail" TEXT NOT NULL,
    "book_url" TEXT NOT NULL,
    "title_vi" TEXT NOT NULL,
    "cover_url" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "UserLibrary_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RefreshToken" (
    "id" TEXT NOT NULL,
    "token" TEXT NOT NULL,
    "userEmail" TEXT NOT NULL,
    "revoked" BOOLEAN NOT NULL DEFAULT false,
    "expires_at" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "RefreshToken_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Account_provider_providerAccountId_key" ON "Account"("provider", "providerAccountId");

-- CreateIndex
CREATE UNIQUE INDEX "Session_sessionToken_key" ON "Session"("sessionToken");

-- CreateIndex
CREATE UNIQUE INDEX "VerificationToken_token_key" ON "VerificationToken"("token");

-- CreateIndex
CREATE UNIQUE INDEX "VerificationToken_identifier_token_key" ON "VerificationToken"("identifier", "token");

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "Book_source_url_key" ON "Book"("source_url");

-- CreateIndex
CREATE UNIQUE INDEX "Book_slug_key" ON "Book"("slug");

-- CreateIndex
CREATE UNIQUE INDEX "Chapter_url_key" ON "Chapter"("url");

-- CreateIndex
CREATE INDEX "Chapter_book_source_url_idx" ON "Chapter"("book_source_url");

-- CreateIndex
CREATE INDEX "Chapter_chapter_no_idx" ON "Chapter"("chapter_no");

-- CreateIndex
CREATE UNIQUE INDEX "CrawlJob_job_id_key" ON "CrawlJob"("job_id");

-- CreateIndex
CREATE UNIQUE INDEX "CrawlJob_bookId_key" ON "CrawlJob"("bookId");

-- CreateIndex
CREATE INDEX "CrawlJob_book_url_idx" ON "CrawlJob"("book_url");

-- CreateIndex
CREATE INDEX "Video_book_url_idx" ON "Video"("book_url");

-- CreateIndex
CREATE INDEX "Video_bookId_idx" ON "Video"("bookId");

-- CreateIndex
CREATE INDEX "ReadingHistory_userEmail_idx" ON "ReadingHistory"("userEmail");

-- CreateIndex
CREATE INDEX "ReadingHistory_book_url_idx" ON "ReadingHistory"("book_url");

-- CreateIndex
CREATE UNIQUE INDEX "ReadingHistory_userEmail_book_url_key" ON "ReadingHistory"("userEmail", "book_url");

-- CreateIndex
CREATE INDEX "UserLibrary_userEmail_idx" ON "UserLibrary"("userEmail");

-- CreateIndex
CREATE INDEX "UserLibrary_book_url_idx" ON "UserLibrary"("book_url");

-- CreateIndex
CREATE UNIQUE INDEX "UserLibrary_userEmail_book_url_key" ON "UserLibrary"("userEmail", "book_url");

-- CreateIndex
CREATE UNIQUE INDEX "RefreshToken_token_key" ON "RefreshToken"("token");

-- CreateIndex
CREATE INDEX "RefreshToken_userEmail_idx" ON "RefreshToken"("userEmail");

-- AddForeignKey
ALTER TABLE "Account" ADD CONSTRAINT "Account_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Chapter" ADD CONSTRAINT "Chapter_book_source_url_fkey" FOREIGN KEY ("book_source_url") REFERENCES "Book"("source_url") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CrawlJob" ADD CONSTRAINT "CrawlJob_bookId_fkey" FOREIGN KEY ("bookId") REFERENCES "Book"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Video" ADD CONSTRAINT "Video_bookId_fkey" FOREIGN KEY ("bookId") REFERENCES "Book"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ReadingHistory" ADD CONSTRAINT "ReadingHistory_userEmail_fkey" FOREIGN KEY ("userEmail") REFERENCES "User"("email") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "UserLibrary" ADD CONSTRAINT "UserLibrary_userEmail_fkey" FOREIGN KEY ("userEmail") REFERENCES "User"("email") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RefreshToken" ADD CONSTRAINT "RefreshToken_userEmail_fkey" FOREIGN KEY ("userEmail") REFERENCES "User"("email") ON DELETE CASCADE ON UPDATE CASCADE;
