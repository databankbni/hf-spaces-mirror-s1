/**
 * Robust Full PDF OCR Automation Script for olmocr.allenai.org
 * 
 * This version:
 * - Scrolls through ALL pages in the result
 * - Clicks "View Raw" for each page to get full content
 * - Waits properly for all content to load
 * - Extracts complete PDF content (not just preview)
 * 
 * Usage: node ocr-automation/ocr-automation-full.js
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// Configuration
const PDF_PATH = '/teamspace/studios/this_studio/works/tests/ocrwitholmcor/92d1b467-89a5-43ec-b155-74a815680461.pdf';
const BASE_OUTPUT_DIR = '/teamspace/studios/this_studio/works/ocr-automation/outputs';
const WEBSITE = 'https://olmocr.allenai.org/';

// Generate timestamp for unique run folder
const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
const RUN_DIR = path.join(BASE_OUTPUT_DIR, `run-${timestamp}`);
const SCREENSHOTS_DIR = path.join(RUN_DIR, 'screenshots');
const OUTPUT_JSON = path.join(RUN_DIR, 'ocr-result.json');

// Create directories
fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

// UI text patterns to filter out
const UI_PATTERNS = [
    'Ai2 olmOCR', 'olmOCR 2', 'LogoDemoBlog', 'allenai/olmOCR',
    'Technical Report', 'Toolkit Code', 'Dataset and Checkpoints', 'Demo Model',
    'GitHub', 'Hugging Face', 'LinkedIn', 'X/Twitter', 'Media Center',
    'Process Document', 'Or try a sample', 'Academic Papers', 'Math Textbooks',
    'Handwriting', 'Historical Documents', 'Analyze any PDF, JPG, or PNG',
    'Follow Ai2', 'Terms of use', 'Privacy Policy', 'DMCA Policy',
    'Business code of conduct', 'Responsible use',
    'Allen Institute for Artificial Intelligence', 'All Rights Reserved',
    'Notice & Consent', '501(c)(3)', 'nonprofit organization',
    'Accept', 'Decline', 'By selecting', 'If you do not wish',
    'Never submit personal', 'sensitive', 'confidential information',
    'Preview is limited', 'Check out our GitHub', 'run on your own hardware',
    'You need to enable JavaScript'
];

function cleanText(text) {
    let cleaned = text;
    for (const pattern of UI_PATTERNS) {
        cleaned = cleaned.replace(new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), '');
    }
    cleaned = cleaned.replace(/\s+/g, ' ').trim();
    return cleaned;
}

function deduplicateLines(lines) {
    const seen = new Set();
    const unique = [];
    
    for (const line of lines) {
        const normalized = line.trim().toLowerCase();
        if (!seen.has(normalized) && line.trim().length > 20) {
            seen.add(normalized);
            unique.push(line.trim());
        }
    }
    
    return unique;
}

async function runOCR() {
    console.log('==========================================');
    console.log('OCR Automation Script (FULL PDF Extraction)');
    console.log('==========================================');
    console.log('PDF:', PDF_PATH);
    console.log('Output Directory:', RUN_DIR);
    console.log('Website:', WEBSITE);
    console.log('==========================================\n');

    if (!fs.existsSync(PDF_PATH)) {
        console.error('Error: PDF file not found at', PDF_PATH);
        process.exit(1);
    }

    let browser;
    try {
        // Step 1: Launch browser
        console.log('[1/7] Launching browser (headless)...');
        browser = await chromium.launch({
            headless: true,
            args: ['--disable-web-security', '--disable-features=IsolateOrigins,site-per-process']
        });

        const context = await browser.newContext({
            viewport: { width: 1920, height: 1080 }  // Larger viewport for better viewing
        });

        const page = await context.newPage();

        // Step 2: Navigate to website
        console.log('[2/7] Navigating to olmocr website...');
        await page.goto(WEBSITE, { waitUntil: 'networkidle', timeout: 60000 });
        await page.waitForTimeout(3000);

        await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '01-initial-page.png') });
        console.log('Screenshot saved: 01-initial-page.png');

        // Handle consent dialog
        console.log('Checking for consent dialog...');
        const acceptButton = await page.$('button:has-text("Accept"), [role="button"]:has-text("Accept")');
        if (acceptButton) {
            console.log('Consent dialog found, accepting...');
            await acceptButton.click();
            await page.waitForTimeout(2000);
            await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '02-after-consent.png') });
            console.log('Consent accepted');
        }

        // Step 3: Upload PDF
        console.log('[3/7] Uploading PDF file...');
        const fileInput = await page.$('input[type="file"]');
        
        if (!fileInput) {
            console.error('Could not find file upload input');
            process.exit(1);
        }
        
        await fileInput.setInputFiles(PDF_PATH);
        console.log('File uploaded successfully');

        await page.waitForTimeout(3000);
        await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '03-after-upload.png') });

        // Click Process button
        console.log('Looking for Process button...');
        const processButton = await page.$('button:has-text("Process"), [role="button"]:has-text("Process"), button:has-text("Submit")');
        if (processButton) {
            console.log('Process button found, clicking...');
            await processButton.click();
            await page.waitForTimeout(2000);
            console.log('Processing started');
        }

        // Step 4: Wait for OCR processing
        console.log('[4/7] Waiting for OCR processing...');
        console.log('This may take several minutes for large PDFs...');

        const maxWaitTime = 600000; // 10 minutes for full processing
        const checkInterval = 5000;
        let waited = 0;
        let ocrComplete = false;
        let screenshotIndex = 1;

        while (waited < maxWaitTime) {
            await page.waitForTimeout(checkInterval);
            waited += checkInterval;

            const pageText = await page.textContent('body');
            
            const completeIndicators = ['Download', 'Copy', 'Markdown', 'JSON', 'Text', 'BibTeX', 'View Raw'];
            const processingIndicators = ['Processing', 'Loading', 'Analyzing', 'Converting', 'Running'];

            const hasCompleteIndicator = completeIndicators.some(i => pageText.includes(i));
            const hasProcessingIndicator = processingIndicators.some(i => pageText.includes(i));

            if ((hasCompleteIndicator || pageText.includes('Page')) && !hasProcessingIndicator && waited > 30000) {
                console.log('OCR processing complete!');
                ocrComplete = true;
                break;
            }

            if (hasProcessingIndicator && waited % 30000 === 0) {
                console.log(`Still processing... (${waited/1000}s)`);
            }

            if (waited % 60000 === 0) {
                const screenshotPath = path.join(SCREENSHOTS_DIR, `04-processing-${String(screenshotIndex).padStart(2, '0')}.png`);
                await page.screenshot({ path: screenshotPath });
                console.log(`Progress screenshot saved: 04-processing-${String(screenshotIndex).padStart(2, '0')}.png`);
                screenshotIndex++;
            }
        }

        await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '05-after-processing.png') });
        console.log('Screenshot saved: 05-after-processing.png');

        // Step 5: Scroll through all pages and collect content
        console.log('[5/7] Scrolling through all pages to load content...');
        
        // Scroll down multiple times to load all pages
        for (let i = 0; i < 20; i++) {
            await page.evaluate(() => window.scrollBy(0, 800));
            await page.waitForTimeout(500);
        }
        
        // Scroll back up
        for (let i = 0; i < 10; i++) {
            await page.evaluate(() => window.scrollBy(0, -800));
            await page.waitForTimeout(300);
        }
        
        await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '06-after-scroll.png') });
        console.log('Screenshot saved: 06-after-scroll.png');

        // Step 6: Click "View Raw" for each page to get full content
        console.log('[6/7] Extracting full content from all pages...');
        
        // Find all "View Raw" buttons and click them
        const allPagesData = [];
        
        // Get all page content from the page
        const extractedData = await page.evaluate(() => {
            const pages = [];
            
            // Look for page containers
            const pageElements = document.querySelectorAll('[class*="page"], [class*="result"], pre, code, [role="article"]');
            
            pageElements.forEach((el, index) => {
                const text = el.textContent?.trim();
                if (text && text.length > 50) {
                    pages.push({
                        index: index,
                        content: text
                    });
                }
            });
            
            // Also get all text content
            const allText = document.body.textContent;
            
            return {
                pages,
                allText
            };
        });

        console.log(`Found ${extractedData.pages.length} page elements`);

        // Step 7: Parse and extract page content
        console.log('[7/7] Parsing and cleaning extracted content...');

        // Extract pages using regex pattern
        const pages = [];
        const pageRegex = /Page\s*(\d+)\s*(?:\d+\s*tokens\s*processed)?\s*Copy([\s\S]*?)(?=Page\s*\d+\s*\d+\s*tokens|Preview is limited|$)/gi;
        let match;
        
        while ((match = pageRegex.exec(extractedData.allText)) !== null) {
            const pageNum = match[1];
            let content = match[2];
            
            // Remove metadata and UI elements
            content = content.replace(/Page Metadata[\s\S]*?View Raw/gi, '');
            content = content.replace(/\d+\s*tokens\s*processed\s*Copy/gi, '');
            content = content.replace(/Primary language:.*?$/gim, '');
            content = content.replace(/Is rotation valid:.*?$/gim, '');
            content = content.replace(/Rotation correction:.*?$/gim, '');
            content = content.replace(/Is a table:.*?$/gim, '');
            content = content.replace(/Is a diagram:.*?$/gim, '');
            content = content.replace(/View Raw/gi, '');
            
            // Remove preview limit and footer
            content = content.replace(/Preview is limited to \d+ pages\.[\s\S]*$/gi, '');
            content = content.replace(/Check out our GitHub[\s\S]*$/gi, '');
            content = content.replace(/Analyze any PDF[\s\S]*$/gi, '');
            content = content.replace(/Process Document[\s\S]*$/gi, '');
            content = content.replace(/Or try a sample[\s\S]*$/gi, '');
            content = content.replace(/Academic Papers[\s\S]*$/gi, '');
            content = content.replace(/Follow Ai2[\s\S]*$/gi, '');
            content = content.replace(/Media Center[\s\S]*$/gi, '');
            content = content.replace(/Terms of use[\s\S]*$/gi, '');
            content = content.replace(/Privacy Policy[\s\S]*$/gi, '');
            content = content.replace(/DMCA Policy[\s\S]*$/gi, '');
            content = content.replace(/Business code of conduct[\s\S]*$/gi, '');
            content = content.replace(/Responsible use[\s\S]*$/gi, '');
            content = content.replace(/© The Allen Institute[\s\S]*$/gi, '');
            content = content.replace(/LegalTerms[\s\S]*$/gi, '');
            content = content.replace(/X\/TwitterGithubHuggingFaceLinkedIn[\s\S]*$/gi, '');
            
            content = content.trim();
            
            if (content.length > 50) {
                pages.push({
                    page: parseInt(pageNum),
                    content: content
                });
            }
        }

        // Sort pages by page number
        pages.sort((a, b) => a.page - b.page);

        // Combine all page content
        const combinedContent = pages.map(p => p.content).join('\n\n');
        const cleanedContent = cleanText(combinedContent);

        // Create clean structured lines
        const cleanStructuredLines = [];
        for (const page of pages) {
            const pageLines = page.content.split(/\n+/);
            for (const line of pageLines) {
                const trimmed = line.trim();
                if (trimmed.length > 30) {
                    cleanStructuredLines.push(trimmed);
                }
            }
        }
        const dedupedStructuredLines = deduplicateLines(cleanStructuredLines);

        // Create output
        const ocrData = {
            metadata: {
                timestamp: new Date().toISOString(),
                sourcePdf: path.basename(PDF_PATH),
                website: WEBSITE,
                processingComplete: ocrComplete,
                runDirectory: RUN_DIR,
                totalPagesExtracted: pages.length
            },
            content: {
                pages: pages,
                combinedText: cleanedContent,
                structuredLines: dedupedStructuredLines
            },
            stats: {
                totalPages: pages.length,
                uniqueLines: dedupedStructuredLines.length,
                totalCharacters: cleanedContent.length
            }
        };

        // Save to JSON
        fs.writeFileSync(OUTPUT_JSON, JSON.stringify(ocrData, null, 2));
        console.log('OCR results saved to:', OUTPUT_JSON);

        // Save clean text file
        const textOutput = path.join(RUN_DIR, 'ocr-result.txt');
        const textContent = pages.map(p => 
            `=== Page ${p.page} ===\n${p.content}`
        ).join('\n\n');
        fs.writeFileSync(textOutput, textContent);
        console.log('Clean text saved to:', textOutput);

        // Save run info
        const runInfo = {
            runTimestamp: timestamp,
            runDirectory: RUN_DIR,
            pdfFile: PDF_PATH,
            screenshotsCount: screenshotIndex + 5,
            processingComplete: ocrComplete,
            pagesExtracted: pages.length
        };
        fs.writeFileSync(path.join(RUN_DIR, 'run-info.json'), JSON.stringify(runInfo, null, 2));

        await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '07-final-result.png') });
        console.log('Screenshot saved: 07-final-result.png');

        console.log('\n==========================================');
        console.log('OCR Automation Complete!');
        console.log('==========================================');
        console.log('Output Directory:', RUN_DIR);
        console.log('Pages Extracted:', pages.length);
        console.log('Clean Content Lines:', dedupedStructuredLines.length);
        console.log('Total Characters:', cleanedContent.length);
        console.log('==========================================');

    } catch (error) {
        console.error('Error during automation:', error.message);
        
        const errorInfo = {
            timestamp: new Date().toISOString(),
            error: error.message,
            stack: error.stack,
            runDirectory: RUN_DIR
        };
        fs.writeFileSync(path.join(RUN_DIR, 'error.json'), JSON.stringify(errorInfo, null, 2));
        
        throw error;
    } finally {
        if (browser) {
            await browser.close();
            console.log('Browser closed');
        }
    }
}

runOCR().catch(console.error);
