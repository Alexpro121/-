"""
FLVS - Full Link Verification System
Система повної перевірки посилань для Rozdum Bot
"""

import re
import requests
import validators
try:
    import whois
except ImportError:
    try:
        import python_whois as whois
    except ImportError:
        whois = None
import tldextract
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
import json
import logging
import time
import dns.resolver
import ssl
import socket
from bs4 import BeautifulSoup
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import hashlib
import base64

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FLVSAnalyzer:
    """Основной класс для анализа ссылок"""
    
    def __init__(self):
        self.trusted_domains = [
            'telegram.org', 'telegram.me', 't.me', 'telesco.pe',
            'google.com', 'facebook.com', 'instagram.com', 'twitter.com',
            'github.com', 'stackoverflow.com', 'wikipedia.org',
            'youtube.com', 'reddit.com', 'linkedin.com'
        ]
        
        # Опасные паттерны для фишинга
        self.phishing_patterns = [
            r'te1egram', r'te1gram', r'telegr4m', r'telegr@m',
            r'g00gle', r'g0ogle', r'fac3book', r'faceb00k',
            r'login.*verification', r'verify.*account', r'suspended.*account',
            r'urgent.*action', r'click.*here.*now', r'limited.*time',
            r'telegram.*bot.*token', r'api.*key', r'secret.*code'
        ]
        
        # Подозрительные TLD
        self.suspicious_tlds = [
            'tk', 'ml', 'ga', 'cf', 'gq', 'pw', 'work', 'click',
            'download', 'review', 'racing', 'science', 'party'
        ]
        
        self.driver = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def extract_urls_from_text(self, text: str) -> List[str]:
        """Извлекает все URL из текста"""
        url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        urls = re.findall(url_pattern, text)
        return urls

    def get_domain_age(self, url: str) -> Dict:
        """Получает возраст домена"""
        try:
            if whois is None:
                logger.warning("WHOIS library not available, using fallback age check")
                return {
                    'age_days': 365,  # Assume domain is at least 1 year old if can't check
                    'creation_date': 'unknown',
                    'is_new': False,
                    'is_very_new': False,
                    'registrar': 'unknown',
                    'status': 'fallback'
                }
            
            domain = urlparse(url).netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            
            whois_info = whois.query(domain)
            
            if whois_info and hasattr(whois_info, 'creation_date') and whois_info.creation_date:
                creation_date = whois_info.creation_date
                
                age_days = (datetime.now() - creation_date).days
                
                return {
                    'age_days': age_days,
                    'creation_date': creation_date.strftime('%Y-%m-%d'),
                    'is_new': age_days < 30,
                    'is_very_new': age_days < 7,
                    'registrar': getattr(whois_info, 'registrar', 'unknown'),
                    'status': 'success'
                }
            else:
                return {'status': 'no_creation_date', 'age_days': None}
                
        except Exception as e:
            logger.error(f"Error getting domain age for {url}: {e}")
            return {'status': 'error', 'error': str(e), 'age_days': None}

    def check_domain_similarity(self, url: str) -> Dict:
        """Проверяет схожесть с известными доменами"""
        try:
            domain = urlparse(url).netloc.lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            
            similarities = []
            
            for trusted in self.trusted_domains:
                # Проверка на typosquatting
                if self._is_typosquatting(domain, trusted):
                    similarities.append({
                        'trusted_domain': trusted,
                        'similarity_type': 'typosquatting',
                        'risk_level': 'high'
                    })
                
                # Проверка на схожесть через edit distance
                similarity_score = self._calculate_similarity(domain, trusted)
                if similarity_score > 0.8:
                    similarities.append({
                        'trusted_domain': trusted,
                        'similarity_score': similarity_score,
                        'similarity_type': 'high_similarity',
                        'risk_level': 'medium' if similarity_score < 0.95 else 'high'
                    })
            
            return {
                'domain': domain,
                'similarities': similarities,
                'is_suspicious': len(similarities) > 0,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Error checking domain similarity for {url}: {e}")
            return {'status': 'error', 'error': str(e)}

    def check_redirects(self, url: str) -> Dict:
        """Проверяет перенаправления"""
        try:
            response = self.session.head(url, allow_redirects=True, timeout=10)
            
            redirect_chain = []
            for resp in response.history:
                redirect_chain.append({
                    'from': resp.url,
                    'to': resp.headers.get('Location', ''),
                    'status_code': resp.status_code
                })
            
            final_url = response.url
            has_redirects = len(redirect_chain) > 0
            
            # Проверка на подозрительные перенаправления
            suspicious_redirects = []
            for redirect in redirect_chain:
                if self._is_suspicious_redirect(redirect['from'], redirect['to']):
                    suspicious_redirects.append(redirect)
            
            return {
                'original_url': url,
                'final_url': final_url,
                'has_redirects': has_redirects,
                'redirect_count': len(redirect_chain),
                'redirect_chain': redirect_chain,
                'suspicious_redirects': suspicious_redirects,
                'is_suspicious': len(suspicious_redirects) > 0,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Error checking redirects for {url}: {e}")
            return {'status': 'error', 'error': str(e)}

    def check_data_harvesting(self, url: str) -> Dict:
        """Проверяет на сбор данных"""
        try:
            response = self.session.get(url, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Проверка форм
            forms = soup.find_all('form')
            suspicious_forms = []
            
            for form in forms:
                form_analysis = self._analyze_form(form)
                if form_analysis['is_suspicious']:
                    suspicious_forms.append(form_analysis)
            
            # Проверка на JavaScript для сбора данных
            scripts = soup.find_all('script')
            suspicious_scripts = []
            
            for script in scripts:
                if script.string:
                    if self._is_suspicious_script(script.string):
                        suspicious_scripts.append({
                            'type': 'data_collection',
                            'content': script.string[:200] + '...'
                        })
            
            # Проверка на скрытые элементы
            hidden_elements = soup.find_all(attrs={'style': re.compile(r'display:\s*none|visibility:\s*hidden')})
            
            return {
                'url': url,
                'forms_count': len(forms),
                'suspicious_forms': suspicious_forms,
                'suspicious_scripts': suspicious_scripts,
                'hidden_elements_count': len(hidden_elements),
                'is_suspicious': len(suspicious_forms) > 0 or len(suspicious_scripts) > 0,
                'uses_https': url.startswith('https://'),
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Error checking data harvesting for {url}: {e}")
            return {'status': 'error', 'error': str(e)}

    def check_phishing_and_malware(self, url: str) -> Dict:
        """Проверяет на фишинг и вредоносный код"""
        try:
            response = self.session.get(url, timeout=15)
            content = response.text.lower()
            
            # Проверка на фишинговые паттерны
            phishing_matches = []
            for pattern in self.phishing_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    phishing_matches.append(pattern)
            
            # Проверка на подозрительные элементы
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Проверка мета-тегов
            meta_analysis = self._analyze_meta_tags(soup)
            
            # Проверка на iframe
            iframes = soup.find_all('iframe')
            suspicious_iframes = []
            for iframe in iframes:
                src = iframe.get('src', '')
                if src and self._is_suspicious_iframe(src):
                    suspicious_iframes.append(src)
            
            # Проверка на подозрительные ссылки
            links = soup.find_all('a', href=True)
            suspicious_links = []
            for link in links:
                href = link['href']
                if self._is_suspicious_link(href):
                    suspicious_links.append(href)
            
            risk_score = self._calculate_phishing_risk_score(
                phishing_matches, suspicious_iframes, suspicious_links, meta_analysis
            )
            
            return {
                'url': url,
                'phishing_patterns': phishing_matches,
                'suspicious_iframes': suspicious_iframes,
                'suspicious_links': suspicious_links[:5],  # Ограничиваем вывод
                'meta_analysis': meta_analysis,
                'risk_score': risk_score,
                'is_phishing': risk_score >= 0.7,
                'is_suspicious': risk_score >= 0.4,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Error checking phishing for {url}: {e}")
            return {'status': 'error', 'error': str(e)}

    def check_telegram_theft(self, url: str) -> Dict:
        """Проверяет на кражу Telegram аккаунтов"""
        try:
            response = self.session.get(url, timeout=15)
            content = response.text.lower()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Паттерны для кражи Telegram аккаунтов
            telegram_theft_patterns = [
                r'telegram.*login', r'telegram.*auth', r'telegram.*verify',
                r'telegram.*code', r'telegram.*token', r'telegram.*api',
                r'enter.*phone.*number', r'verification.*code',
                r'telegram.*session', r'telegram.*account.*suspended',
                r'telegram.*security.*alert', r'telegram.*premium.*free'
            ]
            
            theft_indicators = []
            for pattern in telegram_theft_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    theft_indicators.append(pattern)
            
            # Проверка на поля ввода телефона и кода
            phone_inputs = soup.find_all('input', attrs={'type': 'tel'}) + \
                          soup.find_all('input', attrs={'placeholder': re.compile(r'phone|телефон|код|code', re.I)})
            
            # Проверка на подозрительные формы авторизации
            auth_forms = soup.find_all('form')
            suspicious_auth_forms = []
            
            for form in auth_forms:
                form_text = form.get_text().lower()
                if any(word in form_text for word in ['telegram', 'телеграм', 'login', 'auth', 'verify']):
                    suspicious_auth_forms.append({
                        'action': form.get('action', ''),
                        'method': form.get('method', ''),
                        'inputs': len(form.find_all('input'))
                    })
            
            # Проверка на JavaScript для кражи данных
            scripts = soup.find_all('script')
            suspicious_js = []
            
            for script in scripts:
                if script.string:
                    if any(keyword in script.string.lower() for keyword in [
                        'telegram', 'phone', 'code', 'localStorage', 'sessionStorage',
                        'document.cookie', 'navigator.clipboard'
                    ]):
                        suspicious_js.append('data_theft_script')
            
            risk_score = len(theft_indicators) * 0.2 + len(suspicious_auth_forms) * 0.3 + len(suspicious_js) * 0.1
            
            return {
                'url': url,
                'theft_indicators': theft_indicators,
                'phone_inputs_count': len(phone_inputs),
                'suspicious_auth_forms': suspicious_auth_forms,
                'suspicious_js_count': len(suspicious_js),
                'risk_score': min(risk_score, 1.0),
                'is_telegram_theft': risk_score >= 0.6,
                'is_suspicious': risk_score >= 0.3,
                'status': 'success'
            }
            
        except Exception as e:
            logger.error(f"Error checking Telegram theft for {url}: {e}")
            return {'status': 'error', 'error': str(e)}

    def analyze_url(self, url: str) -> Dict:
        """Полный анализ URL"""
        if not validators.url(url):
            return {'status': 'invalid_url', 'error': 'Invalid URL format'}
        
        analysis_results = {
            'url': url,
            'timestamp': datetime.now().isoformat(),
            'domain_age': self.get_domain_age(url),
            'domain_similarity': self.check_domain_similarity(url),
            'redirects': self.check_redirects(url),
            'data_harvesting': self.check_data_harvesting(url),
            'phishing_malware': self.check_phishing_and_malware(url),
            'telegram_theft': self.check_telegram_theft(url)
        }
        
        # Общая оценка безопасности
        safety_score = self._calculate_overall_safety_score(analysis_results)
        
        analysis_results['safety_score'] = safety_score
        analysis_results['is_safe'] = safety_score >= 0.7
        analysis_results['recommendation'] = self._get_recommendation(safety_score)
        
        return analysis_results

    def _is_typosquatting(self, domain: str, trusted_domain: str) -> bool:
        """Проверяет на typosquatting"""
        if len(domain) != len(trusted_domain):
            return False
        
        diff_count = sum(1 for a, b in zip(domain, trusted_domain) if a != b)
        return 1 <= diff_count <= 2

    def _calculate_similarity(self, domain1: str, domain2: str) -> float:
        """Вычисляет схожесть доменов"""
        vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 3))
        try:
            tfidf_matrix = vectorizer.fit_transform([domain1, domain2])
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return similarity
        except:
            return 0.0

    def _is_suspicious_redirect(self, from_url: str, to_url: str) -> bool:
        """Проверяет подозрительность перенаправления"""
        from_domain = urlparse(from_url).netloc
        to_domain = urlparse(to_url).netloc
        
        # Проверка на перенаправление на подозрительные домены
        if to_domain in self.suspicious_tlds:
            return True
        
        # Проверка на изменение протокола с HTTPS на HTTP
        if from_url.startswith('https://') and to_url.startswith('http://'):
            return True
        
        return False

    def _analyze_form(self, form) -> Dict:
        """Анализирует форму на подозрительность"""
        inputs = form.find_all('input')
        input_types = [inp.get('type', '') for inp in inputs]
        
        suspicious_inputs = ['password', 'tel', 'email']
        has_suspicious_inputs = any(inp_type in suspicious_inputs for inp_type in input_types)
        
        form_action = form.get('action', '')
        suspicious_action = not form_action or form_action.startswith('javascript:')
        
        return {
            'input_count': len(inputs),
            'input_types': input_types,
            'has_suspicious_inputs': has_suspicious_inputs,
            'suspicious_action': suspicious_action,
            'is_suspicious': has_suspicious_inputs and suspicious_action
        }

    def _is_suspicious_script(self, script_content: str) -> bool:
        """Проверяет подозрительность скрипта"""
        suspicious_keywords = [
            'document.cookie', 'localStorage', 'sessionStorage',
            'navigator.clipboard', 'screen.', 'location.href',
            'eval(', 'setTimeout(', 'setInterval('
        ]
        
        return any(keyword in script_content for keyword in suspicious_keywords)

    def _analyze_meta_tags(self, soup) -> Dict:
        """Анализирует мета-теги"""
        meta_tags = soup.find_all('meta')
        
        suspicious_meta = []
        for meta in meta_tags:
            name = meta.get('name', '').lower()
            content = meta.get('content', '').lower()
            
            if 'refresh' in name and 'url=' in content:
                suspicious_meta.append('suspicious_refresh')
            
            if 'robots' in name and 'noindex' in content:
                suspicious_meta.append('noindex_robots')
        
        return {
            'total_meta_tags': len(meta_tags),
            'suspicious_meta': suspicious_meta,
            'is_suspicious': len(suspicious_meta) > 0
        }

    def _is_suspicious_iframe(self, src: str) -> bool:
        """Проверяет подозрительность iframe"""
        return src.startswith('javascript:') or 'data:' in src

    def _is_suspicious_link(self, href: str) -> bool:
        """Проверяет подозрительность ссылки"""
        return href.startswith('javascript:') or href.startswith('data:')

    def _calculate_phishing_risk_score(self, phishing_matches, suspicious_iframes, suspicious_links, meta_analysis) -> float:
        """Вычисляет риск фишинга"""
        score = 0.0
        
        # Фишинговые паттерны
        score += len(phishing_matches) * 0.3
        
        # Подозрительные iframe
        score += len(suspicious_iframes) * 0.2
        
        # Подозрительные ссылки  
        score += len(suspicious_links) * 0.1
        
        # Мета-теги
        if meta_analysis['is_suspicious']:
            score += 0.2
        
        return min(score, 1.0)

    def _calculate_overall_safety_score(self, analysis_results: Dict) -> float:
        """Вычисляет общий балл безопасности"""
        score = 1.0
        
        # Возраст домена
        domain_age = analysis_results['domain_age']
        if domain_age['status'] == 'success' and domain_age['age_days'] is not None:
            if domain_age['is_very_new']:
                score -= 0.3
            elif domain_age['is_new']:
                score -= 0.2
        
        # Схожесть доменов
        if analysis_results['domain_similarity']['is_suspicious']:
            score -= 0.3
        
        # Перенаправления
        if analysis_results['redirects']['is_suspicious']:
            score -= 0.2
        
        # Сбор данных
        if analysis_results['data_harvesting']['is_suspicious']:
            score -= 0.3
        
        # Фишинг
        if analysis_results['phishing_malware']['is_phishing']:
            score -= 0.4
        elif analysis_results['phishing_malware']['is_suspicious']:
            score -= 0.2
        
        # Кража Telegram
        if analysis_results['telegram_theft']['is_telegram_theft']:
            score -= 0.5
        elif analysis_results['telegram_theft']['is_suspicious']:
            score -= 0.3
        
        return max(score, 0.0)

    def _get_recommendation(self, safety_score: float) -> str:
        """Получает рекомендацию по безопасности"""
        if safety_score >= 0.8:
            return "Ссылка безопасна"
        elif safety_score >= 0.6:
            return "Ссылка относительно безопасна, будьте осторожны"
        elif safety_score >= 0.4:
            return "Ссылка подозрительна, не рекомендуется переходить"
        else:
            return "Ссылка опасна, не переходите по ней"

    def __del__(self):
        """Закрытие ресурсов"""
        if self.driver:
            self.driver.quit()
        if self.session:
            self.session.close()


# Функция для быстрого анализа
def analyze_link(url: str) -> Dict:
    """Быстрый анализ ссылки"""
    analyzer = FLVSAnalyzer()
    return analyzer.analyze_url(url)


# Функция для извлечения и анализа всех ссылок из текста
def analyze_text_links(text: str) -> List[Dict]:
    """Анализирует все ссылки в тексте"""
    analyzer = FLVSAnalyzer()
    urls = analyzer.extract_urls_from_text(text)
    
    results = []
    for url in urls:
        result = analyzer.analyze_url(url)
        results.append(result)
    
    return results


if __name__ == "__main__":
    # Тестирование
    test_url = input("Введите URL для анализа: ")
    result = analyze_link(test_url)
    print(json.dumps(result, indent=2, ensure_ascii=False))