from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import re
import time
import random
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

class EmailScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def extract_emails_from_text(self, text):
        """Extract emails with regex."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
        return list(set(re.findall(email_pattern, text)))

    def normalize_obfuscation(self, text):
        """Handle simple obfuscations like 'name [at] company [dot] com'."""
        if not text:
            return text
        replacements = [
            (" [at] ", "@"), (" (at) ", "@"), (" at ", " @ "),
            (" [dot] ", "."), (" (dot) ", "."), (" dot ", "."),
            ("[at]", "@"), ("(at)", "@"),
            ("[dot]", "."), ("(dot)", "."),
        ]
        lowered = text
        for old, newv in replacements:
            lowered = lowered.replace(old, newv)
        return lowered

    def same_domain(self, base_url, candidate_url):
        """Only follow links within the same registrable domain."""
        try:
            base = urlparse(base_url)
            cand = urlparse(candidate_url)
            return base.netloc.split(':')[0].lower().endswith(base.netloc.split(':')[0].lower())
        except Exception:
            return True  # fallback: allow

    def scrape_company_website(self, company_url, max_pages=20):
        """Scrape company website for likely employee emails."""
        emails = []
        visited = set()
        queue = [company_url]

        # Keywords for pages that often contain people details
        keywords = [
            'team', 'about', 'staff', 'employees', 'employee', 'people',
            'leadership', 'management', 'our-team', 'company', 'contact',
            'careers', 'directory', 'faculty', 'researchers'
        ]

        base = company_url

        pages_processed = 0
        while queue and pages_processed < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            pages_processed += 1

            try:
                res = self.session.get(url, timeout=12)
                res.raise_for_status()
                soup = BeautifulSoup(res.content, 'html.parser')

                # 1) Extract mailto: links directly
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if href.lower().startswith('mailto:'):
                        mail = href.split(':', 1)[1].split('?')[0]
                        if mail:
                            emails.append(mail.strip())

                # 2) Extract visible text and de-obfuscate
                page_text = soup.get_text(" ", strip=True)
                cleaned = self.normalize_obfuscation(page_text)

                emails.extend(self.extract_emails_from_text(page_text))
                emails.extend(self.extract_emails_from_text(cleaned))

                # 3) Follow likely relevant links (same domain, keyword matched)
                for a in soup.find_all('a', href=True):
                    href = a['href'].strip()
                    if not href or href.lower().startswith('mailto:'):
                        continue

                    full = urljoin(url, href)
                    if not self.same_domain(base, full):
                        continue

                    if any(k in href.lower() for k in keywords):
                        if full not in visited and full not in queue and len(queue) < 30:
                            queue.append(full)

                # Be respectful with delays
                time.sleep(random.uniform(1.5, 3.5))

            except Exception:
                # Ignore errors (timeouts, 403, etc.) and continue
                continue

        # Deduplicate and filter
        emails = list(set(e.strip() for e in emails if e and '@' in e))

        return emails

    def validate_email_format(self, email, allow_generic=False):
        """Validate email format; optionally filter generic inboxes."""
        if not email:
            return False

        if not allow_generic:
            generic = ['info@', 'contact@', 'support@', 'admin@', 'noreply@', 'no-reply@']
            if any(email.lower().startswith(g) for g in generic):
                return False

        pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
        return re.match(pattern, email) is not None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/scrape', methods=['POST'])
def scrape_emails():
    try:
        data = request.get_json()
        company_url = data.get('company_url', '').strip()
        company_name = data.get('company_name', '').strip()

        if not company_url:
            return jsonify({'error': 'Company URL is required'}), 400

        if not company_url.startswith(('http://', 'https://')):
            company_url = 'https://' + company_url

        scraper = EmailScraper()

        raw_emails = scraper.scrape_company_website(company_url, max_pages=20)

        # Validate and structure
        results = []
        seen = set()
        for e in raw_emails:
            if scraper.validate_email_format(e, allow_generic=False) and e not in seen:
                seen.add(e)
                results.append({
                    'email': e,
                    'source': 'company_website',
                    'domain': e.split('@', 1)[1] if '@' in e else ''
                })

        return jsonify({
            'success': True,
            'emails': results,
            'total_found': len(results),
            'company_url': company_url,
            'company_name': company_name
        })

    except Exception as ex:
        return jsonify({'error': str(ex)}), 500


if __name__ == '__main__':
    # If localhost fails, you can change to: app.run(debug=True, host="0.0.0.0", port=5001)
    app.run(debug=True)