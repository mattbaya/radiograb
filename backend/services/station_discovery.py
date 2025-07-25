"""
Station Discovery Service
Crawls radio station websites to find streaming URLs and calendar information
"""
import requests
from bs4 import BeautifulSoup
import re
import json
import sys
from urllib.parse import urljoin, urlparse
import logging
from typing import Dict, List, Optional, Tuple
from stream_tester import StreamTester

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StreamingURLPattern:
    """Common patterns for finding streaming URLs"""
    
    AUDIO_EXTENSIONS = ['.mp3', '.m3u', '.pls', '.aac', '.ogg']
    STREAMING_DOMAINS = ['icecast', 'shoutcast', 'streamguys', 'tritondigital', 'radiojar']
    STREAMING_PORTS = ['8000', '8080', '80', '443']
    
    @staticmethod
    def get_stream_patterns():
        """Return regex patterns for finding streaming URLs"""
        return [
            # Direct streaming URLs with audio extensions
            r'https?://[^"\s]+\.(?:mp3|m3u8|m3u|pls|aac|ogg|wav|flac)(?:\?[^"\s]*)?',
            # Icecast/Shoutcast patterns (specific ports)
            r'https?://[^"\s]*:(?:8000|8080|8443|1935)/[^"\s]*',
            # Known streaming service domains (high priority)
            r'https?://streams\.radiomast\.io/[^"\s]+',
            r'https?://[^"\s]*\.radiomast\.io/[^"\s]+',
            r'https?://[^"\s]*streamguys[^"\s]*\.com/[^"\s]+',
            r'https?://[^"\s]*tritondigital[^"\s]*\.com/[^"\s]+',
            r'https?://[^"\s]*shoutcast[^"\s]*\.com/[^"\s]+',
            r'https?://[^"\s]*icecast[^"\s]*\.org/[^"\s]+',
            r'https?://[^"\s]*radiojar[^"\s]*\.com/[^"\s]+',
            r'https?://playerservices\.streamtheworld\.com/[^"\s]+',
            r'https?://[^"\s]*\.streamtheworld\.com/[^"\s]+',
            # NPR and public radio streaming
            r'https?://[^"\s]*npr[^"\s]*\.org/[^"\s]*stream[^"\s]*',
            r'https?://cpa\.ds\.npr\.org/[^"\s]+',
            # Audio file extensions in URLs
            r'https?://[^"\s]*(?:stream|live|listen|radio|audio)[^"\s]*\.(?:mp3|m3u8|m3u|pls|aac)',
            # HLS and DASH streaming
            r'https?://[^"\s]*\.m3u8(?:\?[^"\s]*)?',
            r'https?://[^"\s]*hls[^"\s]*\.(?:m3u8|m3u)',
            # Generic streaming patterns (more restrictive)
            r'https?://(?:stream|streams|live|audio|radio)\.[^"\s]*\.[^"\s]+/[^"\s]*',
        ]

class StationDiscovery:
    """Main station discovery service"""
    
    def __init__(self, timeout: int = 10, test_streams: bool = True):
        self.timeout = timeout
        self.test_streams = test_streams
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RadioGrab/1.0 (Station Discovery Bot)'
        })
        if self.test_streams:
            self.stream_tester = StreamTester()
    
    def discover_station(self, website_url: str) -> Dict:
        """
        Discover streaming information for a radio station
        
        Args:
            website_url: The radio station's website URL
            
        Returns:
            Dictionary containing discovered information
        """
        result = {
            'success': True,
            'website_url': website_url,
            'stream_url': None,
            'stream_urls': [],
            'calendar_url': None,
            'logo_url': None,
            'station_name': None,
            'call_letters': None,
            'frequency': None,
            'location': None,
            'description': None,
            'social_links': {},
            'discovered_links': [],
            'stream_test_results': {},
            'recommended_recording_tool': None,
            'stream_compatibility': 'unknown',
            'errors': []
        }
        
        try:
            # Fetch the main page
            logger.info(f"Discovering station: {website_url}")
            response = self._fetch_page(website_url)
            if not response:
                result['success'] = False
                result['errors'].append("Could not fetch website")
                
                # Try to provide basic info from URL even if website is unreachable
                result.update(self._extract_info_from_url(website_url))
                return result
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract basic station information
            result['station_name'] = self._extract_station_name(soup)
            result['call_letters'] = self._extract_call_letters(soup, website_url)
            result['frequency'] = self._extract_frequency(soup)
            result['location'] = self._extract_location(soup)
            result['description'] = self._extract_description(soup)
            result['logo_url'] = self._extract_logo(soup, website_url)
            result['social_links'] = self._extract_social_links(soup)
            result['discovered_links'] = self._extract_navigation_links(soup, website_url)
            
            # Find streaming URLs
            stream_urls = self._find_streaming_urls(soup, website_url)
            result['stream_urls'] = stream_urls
            result['stream_url'] = self._select_best_stream(stream_urls)
            
            # Test discovered streams if enabled
            if self.test_streams and result['stream_url']:
                logger.info(f"Testing discovered stream: {result['stream_url']}")
                stream_test = self.stream_tester.test_stream_quick(result['stream_url'])
                result['stream_test_results'] = stream_test
                result['recommended_recording_tool'] = stream_test.get('recommended_tool')
                result['stream_compatibility'] = 'compatible' if stream_test.get('compatible', False) else 'incompatible'
                
                if not stream_test.get('compatible', False):
                    logger.warning(f"Primary stream not compatible, testing alternatives...")
                    # Try other discovered streams
                    for alt_url in stream_urls:
                        if alt_url != result['stream_url']:
                            alt_test = self.stream_tester.test_stream_quick(alt_url)
                            if alt_test.get('compatible', False):
                                logger.info(f"Found compatible alternative stream: {alt_url}")
                                result['stream_url'] = alt_url
                                result['stream_test_results'] = alt_test
                                result['recommended_recording_tool'] = alt_test.get('recommended_tool')
                                result['stream_compatibility'] = 'compatible'
                                break
            
            # Find calendar/schedule information
            result['calendar_url'] = self._find_calendar_url(soup, website_url)
            
            logger.info(f"Discovery complete for {website_url}")
            if result.get('stream_compatibility') == 'compatible':
                logger.info(f"✅ Stream compatible with {result.get('recommended_recording_tool')}")
            elif result.get('stream_compatibility') == 'incompatible':
                logger.warning(f"❌ No compatible recording tools found")
            
        except Exception as e:
            logger.error(f"Error discovering station {website_url}: {str(e)}")
            result['success'] = False
            result['errors'].append(f"Discovery error: {str(e)}")
            
        return result
    
    def _fetch_page(self, url: str) -> Optional[requests.Response]:
        """Fetch a web page with error handling and fallbacks"""
        # Try different URL variations
        urls_to_try = [url]
        
        # If HTTPS fails, try HTTP
        if url.startswith('https://'):
            urls_to_try.append(url.replace('https://', 'http://'))
        
        # Try with www. prefix if not present
        parsed = urlparse(url)
        if not parsed.netloc.startswith('www.'):
            www_url = f"{parsed.scheme}://www.{parsed.netloc}{parsed.path}"
            urls_to_try.insert(1, www_url)  # Try www. version early
        
        # Try without www. prefix if present
        if parsed.netloc.startswith('www.'):
            no_www_url = f"{parsed.scheme}://{parsed.netloc[4:]}{parsed.path}"
            urls_to_try.insert(1, no_www_url)  # Try non-www version early
        
        for try_url in urls_to_try:
            try:
                logger.info(f"Trying to fetch: {try_url}")
                response = self.session.get(try_url, timeout=self.timeout, allow_redirects=True)
                response.raise_for_status()
                logger.info(f"Successfully fetched: {try_url}")
                return response
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch {try_url}: {str(e)}")
                continue
        
        logger.error(f"All attempts failed for {url}")
        return None
    
    def _extract_station_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract station name from page"""
        # Try title tag first
        title = soup.find('title')
        if title and title.text.strip():
            # Clean up common title patterns
            name = title.text.strip()
            # Remove common suffixes
            for suffix in [' - Home', ' | Home', ' - Radio', ' | Radio', ' - Official Site', ' | Official Site']:
                if name.endswith(suffix):
                    name = name[:-len(suffix)].strip()
            # Remove everything after dash or pipe if still present
            name = re.sub(r'\s*[-|]\s*.*', '', name)
            if name and len(name) < 100:
                return name
        
        # Try h1 tags
        h1 = soup.find('h1')
        if h1 and h1.text.strip():
            text = h1.text.strip()
            if len(text) < 50:
                return text
        
        # Try h2 tags as fallback
        h2 = soup.find('h2')
        if h2 and h2.text.strip():
            text = h2.text.strip()
            if len(text) < 50:
                return text
                
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract station description"""
        # Try meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc['content'].strip()
            
        # Try first paragraph
        p = soup.find('p')
        if p and p.text.strip():
            text = p.text.strip()
            if len(text) > 50:  # Only use if substantial
                return text[:200] + '...' if len(text) > 200 else text
                
        return None
    
    def _extract_logo(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extract station logo URL"""
        # Try common logo selectors
        logo_selectors = [
            'img[alt*="logo" i]',
            'img[src*="logo" i]',
            'img[class*="logo" i]',
            '.logo img',
            '#logo img',
            'header img',
            '.header img'
        ]
        
        for selector in logo_selectors:
            img = soup.select_one(selector)
            if img and img.get('src'):
                return urljoin(base_url, img['src'])
        
        # Try favicon as fallback
        favicon = soup.find('link', rel='icon') or soup.find('link', rel='shortcut icon')
        if favicon and favicon.get('href'):
            return urljoin(base_url, favicon['href'])
            
        return None
    
    def _find_streaming_urls(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find potential streaming URLs on the page with deep discovery"""
        urls = set()
        
        # Search in all text content for direct stream URLs
        page_text = soup.get_text()
        for pattern in StreamingURLPattern.get_stream_patterns():
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            urls.update(matches)
        
        # Search in HTML attributes
        for tag in soup.find_all(['a', 'audio', 'source', 'embed', 'object', 'iframe']):
            for attr in ['href', 'src', 'data', 'value', 'data-src', 'data-stream']:
                url = tag.get(attr)
                if url and self._is_potential_stream_url(url):
                    urls.add(urljoin(base_url, url))
        
        # Look for "Listen Live" buttons and similar
        listen_elements = soup.find_all(string=re.compile(r'listen\s+live|stream|play\s+now', re.I))
        for element in listen_elements:
            parent = element.parent
            if parent and parent.name == 'a' and parent.get('href'):
                href = parent['href']
                if self._is_potential_stream_url(href):
                    urls.add(urljoin(base_url, href))
        
        # Deep discovery: Follow "listen" related links
        listen_page_urls = self._find_listen_pages(soup, base_url)
        for listen_url in listen_page_urls:
            listen_streams = self._crawl_listen_page(listen_url)
            urls.update(listen_streams)
        
        # Look for JavaScript variables containing stream URLs
        script_streams = self._extract_streams_from_scripts(soup)
        urls.update(script_streams)
        
        # Look for embedded players and extract their source URLs
        player_streams = self._extract_streams_from_players(soup, base_url)
        urls.update(player_streams)
        
        return self._validate_stream_urls(list(urls))
    
    def _is_potential_stream_url(self, url: str) -> bool:
        """Check if URL might be a streaming URL"""
        if not url or not url.startswith(('http://', 'https://')):
            return False
            
        url_lower = url.lower()
        
        # Exclude non-audio URLs
        excluded_patterns = [
            'video', 'youtube', 'vimeo', 'facebook.com/video', 'twitter.com', 
            'instagram.com', 'cbsnews.com', 'cnn.com', 'bbc.com/news',
            'playlist-search', 'search', '/news/', '/article/', '/blog/',
            '.jpg', '.png', '.gif', '.jpeg', '.svg', '.pdf', '.doc'
        ]
        
        for pattern in excluded_patterns:
            if pattern in url_lower:
                return False
        
        # High priority streaming services (always include)
        priority_domains = [
            'radiomast.io', 'streamtheworld.com', 'streamguys.com',
            'tritondigital.com', 'radiojar.com', 'icecast.org', 'shoutcast.com'
        ]
        
        for domain in priority_domains:
            if domain in url_lower:
                return True
        
        # Check for audio extensions
        for ext in StreamingURLPattern.AUDIO_EXTENSIONS:
            if ext in url_lower:
                return True
        
        # Check for streaming keywords (but be more selective)
        streaming_keywords = ['stream', 'live', 'radio', 'listen']
        keyword_count = sum(1 for keyword in streaming_keywords if keyword in url_lower)
        
        # Require streaming keywords AND additional indicators
        if keyword_count > 0:
            # Check for streaming ports
            parsed = urlparse(url)
            if parsed.port and str(parsed.port) in StreamingURLPattern.STREAMING_PORTS:
                return True
                
            # Check for streaming-related path patterns
            if any(pattern in url_lower for pattern in ['/stream', '/live', '/radio', '/audio']):
                return True
                
            # Check for known streaming domains
            for domain in StreamingURLPattern.STREAMING_DOMAINS:
                if domain in url_lower:
                    return True
            
        return False
    
    def _validate_stream_urls(self, urls: List[str]) -> List[str]:
        """Validate that URLs are actually streamable"""
        valid_urls = []
        
        for url in urls:
            try:
                # Quick HEAD request to check if URL is accessible
                response = self.session.head(url, timeout=5, allow_redirects=True)
                content_type = response.headers.get('content-type', '').lower()
                
                # Check for audio content types
                if any(audio_type in content_type for audio_type in 
                       ['audio/', 'application/ogg', 'application/x-mpegurl', 'application/vnd.apple.mpegurl']):
                    valid_urls.append(url)
                    logger.info(f"Valid audio stream URL found: {url} (Content-Type: {content_type})")
                elif 'text/plain' in content_type and (url.endswith('.m3u') or url.endswith('.pls')):
                    # Playlist files
                    valid_urls.append(url)
                    logger.info(f"Valid playlist URL found: {url}")
                elif response.status_code == 200:
                    # For known streaming services, trust them even without explicit content-type
                    if any(domain in url.lower() for domain in [
                        'radiomast.io', 'streamtheworld.com', 'streamguys.com',
                        'tritondigital.com', 'radiojar.com', 'icecast.org', 'shoutcast.com'
                    ]):
                        valid_urls.append(url)
                        logger.info(f"Valid streaming service URL found: {url}")
                    
            except requests.RequestException as e:
                logger.debug(f"Could not validate URL {url}: {e}")
                # For known streaming services, include even if we can't validate
                if any(domain in url.lower() for domain in [
                    'radiomast.io', 'streamtheworld.com', 'streamguys.com'
                ]):
                    valid_urls.append(url)
                    logger.info(f"Including trusted streaming service URL: {url}")
                
        return valid_urls
    
    def _select_best_stream(self, stream_urls: List[str]) -> Optional[str]:
        """Select the best streaming URL from candidates"""
        if not stream_urls:
            return None
            
        # Scoring system for stream quality
        scored_urls = []
        
        for url in stream_urls:
            score = 0
            url_lower = url.lower()
            
            # High priority streaming services (highest score)
            if 'streams.radiomast.io' in url_lower:
                score += 50
            elif 'radiomast.io' in url_lower:
                score += 30
            elif 'streamtheworld.com' in url_lower:
                score += 45
            elif 'streamguys.com' in url_lower:
                score += 40
            elif 'tritondigital.com' in url_lower:
                score += 35
            elif 'radiojar.com' in url_lower:
                score += 30
            
            # Prefer direct audio files
            if any(ext in url_lower for ext in ['.mp3', '.aac', '.m3u8']):
                score += 20
            
            # Prefer known streaming services
            if any(service in url_lower for service in ['icecast', 'shoutcast']):
                score += 15
            
            # Prefer standard streaming ports
            if any(port in url for port in [':8000', ':8080', ':1935']):
                score += 10
            
            # Prefer HTTPS
            if url.startswith('https://'):
                score += 5
            
            # Penalize very long URLs
            if len(url) > 200:
                score -= 10
            
            # Penalize URLs with certain patterns that might not be streams
            if any(pattern in url_lower for pattern in [
                'search', 'playlist-search', 'facebook', 'twitter', 'status.xsl', 
                '/admin', '/status', '/stats', 'icecast/status'
            ]):
                score -= 50
            
            scored_urls.append((score, url))
        
        # Return highest scoring URL
        scored_urls.sort(reverse=True)
        return scored_urls[0][1]
    
    def _extract_call_letters(self, soup: BeautifulSoup, website_url: str) -> Optional[str]:
        """Extract call letters (WXXX format) from page content"""
        # Look for call letters in various places
        text_content = soup.get_text()
        
        # Pattern for US radio call letters (3-4 letters starting with W or K)
        call_patterns = [
            r'\b([WK][A-Z]{2,3})\b',  # WXXX or KXXX format
            r'\b([WK][A-Z]{2,3}[-\s]?(?:FM|AM))\b',  # WXXX-FM or WXXX AM
        ]
        
        for pattern in call_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            if matches:
                # Return the most common one or the first one
                call_letters = matches[0] if isinstance(matches[0], str) else matches[0][0]
                # Clean up
                call_letters = re.sub(r'[-\s]?(FM|AM)', '', call_letters, flags=re.IGNORECASE)
                return call_letters.upper()
        
        # Try to extract from domain name
        domain = urlparse(website_url).netloc.lower().replace('www.', '')
        domain_parts = domain.split('.')
        for part in domain_parts:
            if re.match(r'^[wk][a-z]{2,3}$', part, re.IGNORECASE):
                return part.upper()
        
        return None
    
    def _extract_frequency(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract radio frequency (88.1 FM, 1010 AM, etc.)"""
        text_content = soup.get_text()
        
        # Pattern for radio frequencies
        freq_patterns = [
            r'(\d{2,3}\.\d)\s*FM',
            r'(\d{3,4})\s*AM',
            r'(\d{2,3}\.\d)\s*MHz'
        ]
        
        for pattern in freq_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            if matches:
                freq = matches[0]
                if 'mhz' in pattern.lower():
                    return f"{freq} MHz"
                elif 'fm' in pattern.lower():
                    return f"{freq} FM"
                else:
                    return f"{freq} AM"
        
        return None
    
    def _extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract station location/city"""
        text_content = soup.get_text()
        
        # Look for address patterns
        address_pattern = r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z]{2})'
        matches = re.findall(address_pattern, text_content)
        if matches:
            city, state = matches[0]
            return f"{city}, {state}"
        
        # Look in footer or contact info
        footer = soup.find('footer') or soup.find('.footer')
        if footer:
            footer_text = footer.get_text()
            matches = re.findall(address_pattern, footer_text)
            if matches:
                city, state = matches[0]
                return f"{city}, {state}"
        
        return None
    
    def _extract_social_links(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Find social media links"""
        social_links = {}
        social_patterns = {
            'facebook': r'facebook\.com/[^/?]+',
            'twitter': r'twitter\.com/[^/?]+',
            'instagram': r'instagram\.com/[^/?]+',
            'youtube': r'youtube\.com/[^/?]+'
        }
        
        all_links = soup.find_all('a', href=True)
        for link in all_links:
            href = link['href']
            for platform, pattern in social_patterns.items():
                if re.search(pattern, href, re.IGNORECASE):
                    social_links[platform] = href
        
        return social_links
    
    def _extract_navigation_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract all menu/navigation links for manual review"""
        nav_links = []
        
        nav_selectors = [
            'nav a', '.nav a', '.navigation a', '.menu a',
            'header a', '.header a', '.navbar a', '.main-nav a'
        ]
        
        seen_links = set()
        for selector in nav_selectors:
            links = soup.select(selector)
            for link in links:
                href = link.get('href')
                text = link.get_text().strip()
                
                if href and text and href not in seen_links:
                    full_url = urljoin(base_url, href)
                    nav_links.append({
                        'text': text,
                        'url': full_url,
                        'likely_schedule': any(keyword in text.lower() 
                                             for keyword in ['schedule', 'programming', 'shows', 'calendar'])
                    })
                    seen_links.add(href)
        
        return nav_links[:20]  # Limit to first 20 links
    
    def _extract_info_from_url(self, website_url: str) -> Dict:
        """Extract basic information from URL when website is unreachable"""
        parsed = urlparse(website_url)
        domain = parsed.netloc.lower().replace('www.', '')
        
        info = {}
        
        # Try to extract call letters from domain
        domain_parts = domain.split('.')
        for part in domain_parts:
            if re.match(r'^[wk][a-z]{2,3}$', part, re.IGNORECASE):
                call_letters = part.upper()
                info['call_letters'] = call_letters
                info['station_name'] = f"{call_letters} Radio"
                break
        
        # If no call letters found, create name from domain
        if 'station_name' not in info:
            main_domain = domain_parts[0] if domain_parts else domain
            info['station_name'] = main_domain.upper() + " Radio"
        
        # Suggest common URLs that might work
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        info['calendar_url'] = f"{base_domain}/schedule"  # Common schedule URL
        
        return info
    
    def _find_listen_pages(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find pages that might contain streaming information"""
        listen_keywords = [
            'listen', 'stream', 'play', 'live', 'audio', 'player', 
            'ways to listen', 'listen live', 'on air'
        ]
        
        listen_urls = set()
        
        # Look for links with listen-related text or URLs
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().strip().lower()
            
            # Check if link text contains listen keywords
            if any(keyword in text for keyword in listen_keywords):
                full_url = urljoin(base_url, href)
                listen_urls.add(full_url)
                logger.info(f"Found potential listen page: {full_url}")
            
            # Check if URL contains listen keywords
            if any(keyword in href.lower() for keyword in listen_keywords):
                full_url = urljoin(base_url, href)
                listen_urls.add(full_url)
                logger.info(f"Found potential listen URL: {full_url}")
        
        return list(listen_urls)[:5]  # Limit to prevent excessive requests
    
    def _crawl_listen_page(self, listen_url: str) -> List[str]:
        """Crawl a specific listen page for stream URLs"""
        streams = set()
        
        try:
            logger.info(f"Crawling listen page: {listen_url}")
            response = self._fetch_page(listen_url)
            if not response:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Search for stream URLs in this page
            page_text = str(soup)
            for pattern in StreamingURLPattern.get_stream_patterns():
                matches = re.findall(pattern, page_text, re.IGNORECASE)
                streams.update(matches)
            
            # Look for audio/source tags
            for tag in soup.find_all(['audio', 'source', 'embed', 'iframe']):
                for attr in ['src', 'data-src', 'data-stream']:
                    url = tag.get(attr)
                    if url and self._is_potential_stream_url(url):
                        streams.add(urljoin(listen_url, url))
            
            # Look for JavaScript stream configurations
            script_streams = self._extract_streams_from_scripts(soup)
            streams.update(script_streams)
            
            logger.info(f"Found {len(streams)} potential streams on {listen_url}")
            
        except Exception as e:
            logger.warning(f"Error crawling listen page {listen_url}: {e}")
        
        return list(streams)
    
    def _extract_streams_from_scripts(self, soup: BeautifulSoup) -> List[str]:
        """Extract stream URLs from JavaScript code"""
        streams = set()
        
        # Look for JavaScript variables that might contain stream URLs
        script_patterns = [
            # Direct streaming URLs in quotes
            r'["\']https?://[^"\']*(?:stream|live|radio)[^"\']*\.(?:mp3|m3u8|pls|aac)[^"\']*["\']',
            # RadioMast and other streaming services
            r'["\']https?://streams\.radiomast\.io/[^"\']+["\']',
            r'["\']https?://[^"\']*\.radiomast\.io/[^"\']+["\']',
            r'["\']https?://[^"\']*streamtheworld\.com/[^"\']+["\']',
            r'["\']https?://[^"\']*streamguys[^"\']*\.com/[^"\']+["\']',
            # Variable assignments
            r'streamUrl["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'audioUrl["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'stream["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'src["\']?\s*[:=]\s*["\']([^"\']*(?:stream|live|radiomast)[^"\']*)["\']',
            # URLs with ports
            r'["\']https?://[^"\']*:(?:8000|8080|1935|443)/[^"\']*["\']',
            # General patterns for streaming URLs
            r'["\']https?://[^"\']*(?:mp3|m3u8|pls|aac|ogg)[^"\']*["\']'
        ]
        
        for script in soup.find_all('script'):
            if script.string:
                script_content = script.string
                for pattern in script_patterns:
                    matches = re.findall(pattern, script_content, re.IGNORECASE)
                    for match in matches:
                        # If match is a tuple (from capture group), take first element
                        url = match[0] if isinstance(match, tuple) else match
                        # Clean up quotes
                        url = url.strip('\'"')
                        if self._is_potential_stream_url(url):
                            streams.add(url)
                            logger.info(f"Found stream in JavaScript: {url}")
        
        return list(streams)
    
    def _extract_streams_from_players(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract stream URLs from embedded players"""
        streams = set()
        
        # Look for common player patterns
        player_selectors = [
            'iframe[src*="player"]',
            'iframe[src*="stream"]',
            'embed[src*="player"]',
            'object[data*="player"]',
            '.audio-player',
            '.stream-player',
            '#player'
        ]
        
        for selector in player_selectors:
            players = soup.select(selector)
            for player in players:
                # Check various attributes that might contain stream URLs
                for attr in ['src', 'data', 'data-src', 'data-stream', 'href']:
                    url = player.get(attr)
                    if url:
                        full_url = urljoin(base_url, url)
                        if self._is_potential_stream_url(full_url):
                            streams.add(full_url)
                        elif 'player' in url.lower():
                            # Try to extract stream from player page
                            player_streams = self._crawl_player_page(full_url)
                            streams.update(player_streams)
        
        return list(streams)
    
    def _crawl_player_page(self, player_url: str) -> List[str]:
        """Crawl a player page to find the actual stream URL"""
        streams = set()
        
        try:
            logger.info(f"Crawling player page: {player_url}")
            response = self._fetch_page(player_url)
            if not response:
                return []
            
            # Look for stream URLs in the player page
            page_content = response.text
            for pattern in StreamingURLPattern.get_stream_patterns():
                matches = re.findall(pattern, page_content, re.IGNORECASE)
                streams.update(matches)
            
            logger.info(f"Found {len(streams)} streams in player page")
            
        except Exception as e:
            logger.warning(f"Error crawling player page {player_url}: {e}")
        
        return list(streams)
    
    def _find_calendar_url(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find calendar or schedule page URL"""
        calendar_keywords = [
            'schedule', 'calendar', 'programming', 'shows', 'lineup',
            'events', 'timetable', 'program guide'
        ]
        
        # Look for links with calendar-related text
        for keyword in calendar_keywords:
            # Check link text
            link = soup.find('a', string=re.compile(keyword, re.I))
            if link and link.get('href'):
                return urljoin(base_url, link['href'])
            
            # Check alt text and titles
            link = soup.find('a', attrs={'title': re.compile(keyword, re.I)})
            if link and link.get('href'):
                return urljoin(base_url, link['href'])
        
        # Look for common calendar file types
        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            if any(ext in href for ext in ['.ics', '.ical', 'calendar']):
                return urljoin(base_url, link['href'])
        
        return None

def test_station_discovery():
    """Test function for the station discovery service"""
    discovery = StationDiscovery()
    
    # Test with a few radio stations
    test_stations = [
        'https://wehc.com',
        'https://wfpk.org',
        'https://kexp.org'
    ]
    
    for station_url in test_stations:
        print(f"\n=== Testing {station_url} ===")
        result = discovery.discover_station(station_url)
        
        print(f"Name: {result['station_name']}")
        print(f"Stream URL: {result['stream_url']}")
        print(f"Calendar URL: {result['calendar_url']}")
        print(f"Logo URL: {result['logo_url']}")
        print(f"All streams found: {len(result['stream_urls'])}")
        if result['errors']:
            print(f"Errors: {result['errors']}")

def main():
    """CLI interface for station discovery"""
    if len(sys.argv) != 2:
        print(json.dumps({'success': False, 'error': 'Website URL required'}))
        sys.exit(1)
    
    website_url = sys.argv[1]
    discovery = StationDiscovery()
    result = discovery.discover_station(website_url)
    print(json.dumps(result))

if __name__ == "__main__":
    if len(sys.argv) == 2:
        main()
    else:
        # For API usage, always try main() if we have at least one argument
        if len(sys.argv) > 1:
            main()
        else:
            print(json.dumps({'success': False, 'error': 'Website URL required'}))