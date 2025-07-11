"""
Link validation and safety checking system
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

class LinkChecker:
    """Advanced link safety checker with phishing detection"""

    def __init__(self):
        self.phishing_keywords = [
            'urgent', 'verify', 'suspended', 'click now', 'limited time',
            'winner', 'congratulations', 'free money', 'prize',
            'security alert', 'account locked', 'update payment',
            'терміново', 'перевірити', 'заблоковано', 'натисни зараз',
            'переможець', 'вітаємо', 'безкоштовні гроші', 'приз',
            'попередження безпеки', 'акаунт заблоковано'
        ]

        self.suspicious_domains = [
            'bit.ly', 'tinyurl.com', 'goo.gl', 't.co', 'short.link',
            'ow.ly', 'buff.ly', 'tiny.cc', 'rebrand.ly',  # URL shorteners
            'mega.nz', 'mediafire.com', 'sendspace.com',  # File sharing
            'tempmail.org', '10minutemail.com',  # Temporary email
        ]

        self.trusted_domains = [
            'github.com', 'stackoverflow.com', 'wikipedia.org',
            'google.com', 'youtube.com', 'linkedin.com',
            'telegram.org', 'telegram.me', 'facebook.com',
            'twitter.com', 'instagram.com', 'reddit.com',
            'microsoft.com', 'apple.com', 'amazon.com'
        ]

        self.malicious_patterns = [
            r'[0o]{2,}',  # Multiple zeros/Os to confuse users
            r'[il1]{3,}',  # Multiple similar looking characters
            r'[.-]{2,}',  # Multiple dots or dashes
            r'[a-z][A-Z][a-z]',  # Mixed case to confuse
        ]

        # Create requests session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # User agent to avoid bot detection
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def extract_links(self, text: str) -> List[str]:
        """Extract all URLs from text including various formats."""
        patterns = [
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            r'www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),])+\.[a-zA-Z]{2,}',
            r'[a-zA-Z0-9.-]+\.(?:com|org|net|edu|gov|mil|int|co|io|me|tv|cc|tk|ml|ga|cf)(?:/[^\s]*)?'
        ]

        links = []
        for pattern in patterns:
            found = re.findall(pattern, text, re.IGNORECASE)
            for link in found:
                if not link.startswith('http'):
                    if link.startswith('www.'):
                        link = 'https://' + link
                    else:
                        link = 'https://' + link
                links.append(link)

        return list(set(links))  # Remove duplicates

    def check_domain_reputation(self, domain: str) -> Dict:
        """Check domain reputation against known databases."""
        result = {
            'is_malicious': False,
            'reputation_score': 50,  # 0-100, 50 is neutral
            'checks': []
        }

        # Check against suspicious domain list
        if any(sus_domain in domain.lower() for sus_domain in self.suspicious_domains):
            result['reputation_score'] -= 30
            result['checks'].append('Found in suspicious domains list')

        # Check against trusted domain list
        if any(trusted in domain.lower() for trusted in self.trusted_domains):
            result['reputation_score'] += 40
            result['checks'].append('Found in trusted domains list')

        # Check for typosquatting patterns
        for pattern in self.malicious_patterns:
            if re.search(pattern, domain):
                result['reputation_score'] -= 20
                result['checks'].append('Suspicious character patterns detected')
                break

        # Check domain length and structure
        if len(domain) > 50:
            result['reputation_score'] -= 15
            result['checks'].append('Unusually long domain name')

        # Check for excessive subdomains
        if domain.count('.') > 3:
            result['reputation_score'] -= 10
            result['checks'].append('Multiple subdomains detected')

        # Check for suspicious TLDs
        suspicious_tlds = ['.tk', '.ml', '.ga', '.cf', '.pw', '.cc']
        if any(domain.endswith(tld) for tld in suspicious_tlds):
            result['reputation_score'] -= 25
            result['checks'].append('Suspicious top-level domain')

        if result['reputation_score'] < 20:
            result['is_malicious'] = True

        return result

    def check_link_safety(self, url: str) -> Dict:
        """Comprehensive link safety check."""
        result = {
            'url': url,
            'is_safe': True,
            'risk_level': 'low',  # low, medium, high, critical
            'warnings': [],
            'domain': None,
            'final_url': None,
            'reputation': None,
            'response_code': None
        }

        try:
            parsed = urlparse(url)
            result['domain'] = parsed.netloc.lower()

            # Basic URL validation
            if not result['domain']:
                result['is_safe'] = False
                result['risk_level'] = 'critical'
                result['warnings'].append('❌ Invalid URL format')
                return result

            # Check domain reputation
            result['reputation'] = self.check_domain_reputation(result['domain'])

            if result['reputation']['is_malicious']:
                result['is_safe'] = False
                result['risk_level'] = 'critical'
                result['warnings'].append('🚨 Malicious domain detected')
                result['warnings'].extend(result['reputation']['checks'])
                return result

            # Add reputation warnings
            if result['reputation']['reputation_score'] < 40:
                result['risk_level'] = 'high'
                result['warnings'].append('⚠️ Low domain reputation')
            elif result['reputation']['reputation_score'] < 60:
                result['risk_level'] = 'medium'

            # Check for IP addresses
            if re.match(r'^\d+\.\d+\.\d+\.\d+', result['domain']):
                result['warnings'].append('⚠️ Uses IP address instead of domain')
                result['risk_level'] = 'high'

            # Check for non-standard ports
            if ':' in result['domain'] and not result['domain'].endswith(':80') and not result['domain'].endswith(':443'):
                result['warnings'].append('⚠️ Non-standard port detected')
                result['risk_level'] = 'medium'

            # Try to verify link accessibility and check for redirects
            try:
                response = self.session.head(url, allow_redirects=True, timeout=5)
                result['response_code'] = response.status_code
                result['final_url'] = response.url

                if result['final_url'] != url:
                    final_domain = urlparse(result['final_url']).netloc.lower()
                    if final_domain != result['domain']:
                        result['warnings'].append(f'🔄 Redirects to different domain: {final_domain}')

                        # Check if redirect domain is suspicious
                        redirect_rep = self.check_domain_reputation(final_domain)
                        if redirect_rep['is_malicious']:
                            result['is_safe'] = False
                            result['risk_level'] = 'critical'
                            result['warnings'].append('🚨 Redirects to malicious domain')

                # Check response headers for suspicious content
                content_type = response.headers.get('content-type', '').lower()
                if 'application/octet-stream' in content_type or 'application/x-msdownload' in content_type:
                    result['warnings'].append('⚠️ Link downloads executable file')
                    result['risk_level'] = 'high'

            except requests.exceptions.Timeout:
                result['warnings'].append('⏱️ Link response timeout')
                result['risk_level'] = 'medium'
            except requests.exceptions.ConnectionError:
                result['warnings'].append('❌ Cannot connect to link')
                result['risk_level'] = 'high'
            except Exception as e:
                result['warnings'].append('❌ Error verifying link')
                result['risk_level'] = 'high'

            # Final safety assessment
            if result['risk_level'] in ['high', 'critical']:
                result['is_safe'] = False

        except Exception as e:
            logger.error(f"Error checking link safety: {e}")
            result['is_safe'] = False
            result['risk_level'] = 'critical'
            result['warnings'].append('❌ Critical error analyzing link')

        return result

    def check_text_for_phishing(self, text: str) -> Dict:
        """Enhanced phishing detection in text content."""
        result = {
            'is_suspicious': False,
            'risk_score': 0,
            'indicators': [],
            'confidence': 'low'  # low, medium, high
        }

        text_lower = text.lower()

        # Check for phishing keywords with weighted scoring
        high_risk_keywords = ['verify account', 'suspended account', 'click immediately', 'urgent action']
        medium_risk_keywords = ['free money', 'congratulations', 'winner', 'prize']
        low_risk_keywords = ['urgent', 'limited time', 'expire']

        for keyword in high_risk_keywords:
            if keyword in text_lower:
                result['risk_score'] += 30
                result['indicators'].append(f'High-risk keyword: "{keyword}"')

        for keyword in medium_risk_keywords:
            if keyword in text_lower:
                result['risk_score'] += 20
                result['indicators'].append(f'Medium-risk keyword: "{keyword}"')

        for keyword in low_risk_keywords:
            if keyword in text_lower:
                result['risk_score'] += 10
                result['indicators'].append(f'Low-risk keyword: "{keyword}"')

        # Check for urgency patterns
        urgency_patterns = [
            r'act now', r'hurry', r'expire[sd]? (?:today|soon|in \d+)',
            r'immediate(?:ly)?', r'asap', r'right now'
        ]

        urgency_count = 0
        for pattern in urgency_patterns:
            if re.search(pattern, text_lower):
                urgency_count += 1

        if urgency_count > 0:
            result['risk_score'] += urgency_count * 15
            result['indicators'].append(f'Urgency language detected ({urgency_count} instances)')

        # Check for financial offers
        financial_patterns = [
            r'\$\d+(?:,\d{3})*(?:\.\d{2})?',  # Dollar amounts
            r'€\d+(?:,\d{3})*(?:\.\d{2})?',   # Euro amounts
            r'\d+(?:,\d{3})* (?:dollars?|euros?|грн|гривень?)',
            r'free (?:money|cash|bitcoin)',
            r'earn \$?\d+'
        ]

        for pattern in financial_patterns:
            if re.search(pattern, text_lower):
                result['risk_score'] += 25
                result['indicators'].append('Financial offers/amounts detected')
                break

        # Check for credential harvesting attempts
        credential_patterns = [
            r'enter (?:your )?(?:password|login|username)',
            r'verify (?:your )?(?:identity|account|card)',
            r'update (?:your )?(?:payment|billing|card) (?:info|details)',
            r'confirm (?:your )?(?:account|identity)'
        ]

        for pattern in credential_patterns:
            if re.search(pattern, text_lower):
                result['risk_score'] += 35
                result['indicators'].append('Credential harvesting attempt detected')
                break

        # Check for social engineering tactics
        social_patterns = [
            r'(?:you (?:have )?won|congratulations)',
            r'selected (?:as|for)',
            r'special (?:offer|deal|discount)',
            r'limited (?:time|offer)',
            r'exclusive (?:access|offer)'
        ]

        for pattern in social_patterns:
            if re.search(pattern, text_lower):
                result['risk_score'] += 15
                result['indicators'].append('Social engineering tactics detected')
                break

        # Determine confidence and suspicion level
        if result['risk_score'] >= 60:
            result['is_suspicious'] = True
            result['confidence'] = 'high'
        elif result['risk_score'] >= 40:
            result['is_suspicious'] = True
            result['confidence'] = 'medium'
        elif result['risk_score'] >= 20:
            result['confidence'] = 'medium'

        return result

# Global instance
link_checker = LinkChecker()

def validate_message_links(message_text: str) -> Tuple[bool, List[Dict], Dict]:
    """
    Comprehensive validation of all links in a message.
    Returns: (is_safe, link_results, phishing_check)
    """
    links = link_checker.extract_links(message_text)
    link_results = []
    overall_safe = True

    for link in links:
        check_result = link_checker.check_link_safety(link)
        link_results.append(check_result)

        if not check_result['is_safe'] or check_result['risk_level'] in ['high', 'critical']:
            overall_safe = False

    # Check for phishing indicators in text
    phishing_check = link_checker.check_text_for_phishing(message_text)

    if phishing_check['is_suspicious'] and phishing_check['confidence'] in ['medium', 'high']:
        overall_safe = False

    return overall_safe, link_results, phishing_check

def format_link_warning(link_results: List[Dict], phishing_check: Dict) -> str:
    """Format a comprehensive warning message for unsafe content."""
    warning = "🚨 <b>ПОПЕРЕДЖЕННЯ ПРО БЕЗПЕКУ</b>\n\n"

    if phishing_check['is_suspicious']:
        confidence_emoji = {'low': '⚠️', 'medium': '🔶', 'high': '🚨'}
        warning += f"{confidence_emoji[phishing_check['confidence']]} <b>Підозра на фішинг!</b>\n"
        warning += f"📊 Ризик: {phishing_check['risk_score']}/100 ({phishing_check['confidence']} впевненість)\n\n"

        warning += "<b>Виявлені індикатори:</b>\n"
        for indicator in phishing_check['indicators']:
            warning += f"• {indicator}\n"
        warning += "\n"

    if link_results:
        warning += "<b>🔗 Аналіз посилань:</b>\n\n"

        for result in link_results:
            risk_emoji = {
                'low': '🟢',
                'medium': '🟡', 
                'high': '🟠',
                'critical': '🔴'
            }

            warning += f"{risk_emoji[result['risk_level']]} <b>Посилання:</b> {result['url'][:50]}{'...' if len(result['url']) > 50 else ''}\n"
            warning += f"📊 Рівень ризику: {result['risk_level']}\n"

            if result['reputation']:
                warning += f"🎯 Репутація домену: {result['reputation']['reputation_score']}/100\n"

            if result['warnings']:
                warning += "<b>Попередження:</b>\n"
                for warn in result['warnings']:
                    warning += f"  • {warn}\n"
            warning += "\n"

    warning += "🛡️ <b>РЕКОМЕНДАЦІЇ БЕЗПЕКИ:</b>\n"
    warning += "• ❌ НЕ натискайте на підозрілі посилання\n"
    warning += "• 🔐 НЕ вводьте паролі чи особисті дані\n"
    warning += "• 💳 НЕ вводьте дані банківських карт\n"
    warning += "• 📱 Перевірте адресу сайту в браузері\n"
    warning += "• 🤔 Будьте скептичними до занадто хороших пропозицій\n"
    warning += "• 📞 Зверніться до офіційної підтримки при сумнівах\n\n"

    warning += "⚡ <b>Якщо ви вже натиснули на посилання:</b>\n"
    warning += "• 🚪 Негайно закрийте сторінку\n"
    warning += "• 🔄 Змініть паролі в важливих акаунтах\n"
    warning += "• 💳 Перевірте банківські операції\n"
    warning += "• 🛡️ Запустіть антивірусну перевірку\n"

    return warning