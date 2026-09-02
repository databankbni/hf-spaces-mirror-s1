import feedparser
from typing import List
from datetime import datetime
from app.models import Article
import re
import logging

logger = logging.getLogger(__name__)

class RSSParser:
    """RSS feed parser for news sources"""
    
    async def parse_google_news(self, content: str, category: str) -> List[Article]:
        """Parse Google News RSS feed with advanced XML parsing"""
        try:
            articles = []
            
            # Extract items from XML using regex
            item_regex = r'<item>([\s\S]*?)</item>'
            matches = re.findall(item_regex, content)
            
            for item in matches[:20]:  # Limit to 20 articles
                title = self._extract_tag(item, 'title') or 'No title'
                link = self._extract_tag(item, 'link') or self._extract_tag(item, 'guid') or ''
                description = self._extract_tag(item, 'description') or self._extract_tag(item, 'content:encoded') or ''
                pub_date = self._extract_tag(item, 'pubDate') or self._extract_tag(item, 'published') or datetime.now().isoformat()
                creator = self._extract_tag(item, 'dc:creator') or self._extract_tag(item, 'author') or 'Google News'
                
                # Extract image from multiple sources
                image = self._extract_image_from_xml(item, description, category, title)
                
                # Extract source name from description (Google News format: <a href="...">Source</a>)
                source_match = re.search(r'<a[^>]*>([^<]+)</a>', description)
                article_source = source_match.group(1) if source_match else 'Google News'
                
                # Clean description (Google News RSS only contains links, not actual content)
                cleaned_description = self._clean_google_news_description(description)
                
                article = Article(
                    title=self._clean_html(title),
                    description=cleaned_description,
                    url=link,
                    image_url=image, # Corrected: image -> image_url
                    published_at=pub_date, # Corrected: publishedAt -> published_at
                    source=self._clean_html(article_source),
                    category=category
                )
                articles.append(article)
            
            return articles
        except Exception as e:
            logger.error("[RSS] Error parsing Google News: %s", e)
            return []
    
    def _extract_image_from_xml(self, item: str, description: str, category: str, title: str) -> str:
        """Extract image from multiple XML sources with fallbacks"""
        # 1. Try media:content or media:thumbnail with namespace handling
        # Many feeds use media:content URL attribute directly
        media_match = re.search(r'<media:(content|thumbnail)[^>]*url="([^"]+)"', item)
        if media_match:
            return media_match.group(2)
            
        # 2. Try enclosure tag (standard RSS)
        enclosure_match = re.search(r'<enclosure[^>]*url="([^"]+)"', item)
        if enclosure_match:
            return enclosure_match.group(1)
        
        # 3. Try parsing <img> tag from description or content:encoded
        # Look for src attribute in img tags, supporting both single and double quotes
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description)
        if img_match:
            return img_match.group(1)
            
        # 4. Try looking for og:image pattern if inside CDATA
        og_match = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', description)
        if og_match:
            return og_match.group(1)
        
        # 5. Return empty string to let Frontend handle the fallback
        # User requested: "if there is no image came while fetching then we banner our segmento pulse banner"
        # The frontend uses /placeholder-news.svg when image is empty
        return ""
    
    def _clean_google_news_description(self, description: str) -> str:
        """Clean Google News description - they typically only contain links, not actual content"""
        # Check if this is a Google News link-only description
        if 'news.google.com/rss/articles' in description:
            return ''  # No real content, just redirect links
        
        # Try to extract content after the link
        after_link_match = re.search(r'</a>([\s\S]*)', description)
        if after_link_match:
            extracted = self._clean_html(after_link_match.group(1))
            if len(extracted) > 30:
                return extracted[:200]
        
        # Fallback: clean entire description if meaningful
        full_clean = self._clean_html(description)
        if len(full_clean) > 30 and not full_clean.startswith('http'):
            return full_clean[:200]
        
        return ''
    
    def _extract_tag(self, xml: str, tag_name: str) -> str:
        """Extract XML tag content"""
        pattern = f'<{tag_name}[^>]*>([\\s\\S]*?)</{tag_name}>'
        match = re.search(pattern, xml, re.IGNORECASE)
        return match.group(1).strip() if match else ''
    
    def _clean_html(self, html: str) -> str:
        """Remove HTML tags and decode entities"""
        text = html
        
        # Remove CDATA
        text = re.sub(r'<!\[CDATA\[([\s\S]*?)\]\]>', r'\1', text)
        
        # Remove HTML tags (multiple passes for nested tags)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'<[^>]*', '', text)
        text = re.sub(r'>', '', text)
        
        # Decode HTML entities
        entities = {
            '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
            '&quot;': '"', '&#39;': "'", '&apos;': "'",
            '&hellip;': '...', '&mdash;': '—', '&ndash;': '–'
        }
        for entity, char in entities.items():
            text = text.replace(entity, char)
        
        # Remove numeric entities
        text = re.sub(r'&#\d+;', '', text)
        
        # Clean whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    async def parse_provider_rss(self, content: str, provider: str) -> List[Article]:
        """Parse cloud provider RSS feed"""
        try:
            feed = feedparser.parse(content)
            articles = []
            
            for entry in feed.entries[:20]:
                # Extract image
                image_url = self._extract_image_from_entry(entry)
                
                # Parse date
                published_at = self._parse_date(entry.get('published', ''))
                
                # Get description
                description = entry.get('summary', '')
                if description:
                    # Strip HTML tags
                    description = re.sub(r'<[^>]+>', '', description)
                    description = description[:200] + '...' if len(description) > 200 else description
                
                article = Article(
                    title=entry.get('title', ''),
                    description=description,
                    url=entry.get('link', ''),
                    image_url=image_url, # Corrected: image -> image_url
                    published_at=published_at, # Corrected: publishedAt -> published_at
                    source=provider.upper(),
                    category=f'cloud-{provider}'
                )
                articles.append(article)
            
            return articles
        except Exception as e:
            logger.error("[RSS] Error parsing provider feed: %s", e)
            return []
    
    def _extract_image_from_entry(self, entry) -> str:
        """Extract image URL from feed entry"""
        # Try media:content
        if hasattr(entry, 'media_content') and entry.media_content:
            return entry.media_content[0].get('url', '')
        
        # Try media:thumbnail
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            return entry.media_thumbnail[0].get('url', '')
        
        # Try enclosures
        if hasattr(entry, 'enclosures') and entry.enclosures:
            for enclosure in entry.enclosures:
                if enclosure.get('type', '').startswith('image'):
                    return enclosure.get('href', '')
        
        # Try HTML content/summary for <img> tags
        content = ''
        if hasattr(entry, 'content') and entry.content:
            content = entry.content[0].get('value', '')
        elif hasattr(entry, 'summary'):
            content = entry.summary
            
        if content:
            import re
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
            if img_match:
                return img_match.group(1)
        
        # Default: Return empty to let Frontend use standard banner
        return ""
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime"""
        try:
            # feedparser usually provides a parsed date
            # but we'll handle string parsing as fallback
            from dateutil import parser
            return parser.parse(date_str)
        except:
            return datetime.now()
