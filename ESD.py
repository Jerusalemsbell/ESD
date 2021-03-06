# -*- coding: utf-8 -*-

"""
    ESD
    ~~~

    Implements enumeration sub domains

    :author:    Feei <feei@feei.cn>
    :homepage:  https://github.com/FeeiCN/ESD
    :license:   GPL, see LICENSE for more details.
    :copyright: Copyright (c) 2018 Feei. All rights reserved
"""
import os
import re
import sys
import time
import string
import random
import traceback
import itertools
import datetime
import colorlog
import asyncio
import aiodns
import aiohttp
import logging
import requests
import async_timeout
from aiohttp.resolver import AsyncResolver
from itertools import islice
from logging import handlers
from difflib import SequenceMatcher

log_path = 'logs'
if os.path.isdir(log_path) is not True:
    os.mkdir(log_path, 0o755)
logfile = os.path.join(log_path, 'ESD.log')

handler = colorlog.StreamHandler()
formatter = colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s [%(name)s] [%(levelname)s] %(message)s%(reset)s',
    datefmt=None,
    reset=True,
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    },
    secondary_log_colors={},
    style='%'
)
handler.setFormatter(formatter)

file_handler = handlers.RotatingFileHandler(logfile, maxBytes=(1048576 * 5), backupCount=7)
file_handler.setFormatter(formatter)

logger = colorlog.getLogger('ESD')
logger.addHandler(handler)
logger.addHandler(file_handler)
logger.setLevel(logging.DEBUG)


class EnumSubDomain(object):
    def __init__(self, domain):
        self.project_directory = os.path.abspath(os.path.dirname(__file__))
        logger.info('----------')
        logger.info('Start domain: {d}'.format(d=domain))
        self.data = {}
        self.domain = domain
        self.stable_dns_servers = ['114.114.114.114']
        dns_servers = []
        dns_server_config = '{pd}/servers.esd'.format(pd=self.project_directory)
        if not os.path.isfile(dns_server_config):
            logger.critical('ESD/servers.esd file not found!')
            exit(1)
        with open(dns_server_config) as f:
            for s in f:
                dns_servers.append(s.strip())
        if len(dns_servers) == 0:
            logger.info('ESD/servers.esd not configured, The default dns server will be used!')
            dns_servers = self.stable_dns_servers
        random.shuffle(dns_servers)
        self.dns_servers = dns_servers
        self.resolver = None
        self.loop = asyncio.get_event_loop()
        self.general_dicts = []
        # Mark whether the current domain name is a pan-resolved domain name
        self.is_wildcard_domain = False
        # Use a nonexistent domain name to determine whether
        # there is a pan-resolve based on the DNS resolution result
        self.wildcard_sub = 'feei-esd-{random}'.format(random=random.randint(0, 9999))
        # There is no domain name DNS resolution IP
        self.wildcard_ips = []
        # No domain name response HTML
        self.wildcard_html = None
        self.wildcard_html_len = 0
        # Subdomains that are consistent with IPs that do not have domain names
        self.wildcard_subs = []
        # Wildcard domains use RSC
        self.wildcard_domains = {}
        # Corotines count
        self.coroutine_count = None
        self.coroutine_count_dns = 100000
        self.coroutine_count_request = 100
        # RSC ratio
        self.rsc_ratio = 0.8
        self.remainder = 0
        # Reuqest Header
        self.request_headers = {
            'Connection': 'keep-alive',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.186 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'DNT': '1',
            'Referer': 'http://www.baidu.com/robot',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }

    def generate_general_dicts(self, line):
        """
        Generate general subdomains dicts
        :param line:
        :return:
        """
        letter_count = line.count('{letter}')
        number_count = line.count('{number}')
        letters = itertools.product(string.ascii_lowercase, repeat=letter_count)
        letters = [''.join(l) for l in letters]
        numbers = itertools.product(string.digits, repeat=number_count)
        numbers = [''.join(n) for n in numbers]
        for l in letters:
            iter_line = line.replace('{letter}' * letter_count, l)
            self.general_dicts.append(iter_line)
        number_dicts = []
        for gd in self.general_dicts:
            for n in numbers:
                iter_line = gd.replace('{number}' * number_count, n)
                number_dicts.append(iter_line)
        if len(number_dicts) > 0:
            return number_dicts
        else:
            return self.general_dicts

    def load_sub_domain_dict(self):
        """
        Load subdomains from files and dicts
        :return:
        """
        dicts = []
        with open('{pd}/subs.esd'.format(pd=self.project_directory), encoding='utf-8') as f:
            for line in f:
                line = line.strip().lower()
                # skip comments and space
                if '#' in line or line == '':
                    continue
                if '{letter}' in line or '{number}' in line:
                    self.general_dicts = []
                    dicts_general = self.generate_general_dicts(line)
                    dicts += dicts_general
                else:
                    # compatibility other dicts
                    line = line.strip('.')
                    dicts.append(line)
        dicts = list(set(dicts))
        # root domain
        dicts.append('@')
        return dicts

    async def query(self, sub):
        """
        Query domain
        :param sub:
        :return:
        """
        ret = None
        # root domain
        if sub == '@':
            sub_domain = self.domain
        else:
            sub_domain = '{sub}.{domain}'.format(sub=sub, domain=self.domain)
        try:
            ret = await self.resolver.query(sub_domain, 'A')
            ret = [r.host for r in ret]
            domain_ips = [s for s in ret]
            # It is a wildcard domain name and
            # the subdomain IP that is burst is consistent with the IP
            # that does not exist in the domain name resolution,
            # the response similarity is discarded for further processing.
            if self.is_wildcard_domain and sorted(self.wildcard_ips) == sorted(domain_ips):
                logger.debug('{r} maybe wildcard domain, continue RSC {sub}'.format(r=self.remainder, sub=sub_domain, ips=domain_ips))
            else:
                self.data[sub_domain] = sorted(domain_ips)
                logger.info('{r} {sub} {ips}'.format(r=self.remainder, sub=sub_domain, ips=domain_ips))
        except aiodns.error.DNSError as e:
            err_code, err_msg = e.args[0], e.args[1]
            # 1:  DNS server returned answer with no data
            # 4:  Domain name not found
            # 11: Could not contact DNS servers
            # 12: Timeout while contacting DNS servers
            if err_code not in [1, 4, 11, 12]:
                logger.info('{domain} {exception}'.format(domain=sub_domain, exception=e))
        except Exception as e:
            logger.info(sub_domain)
            logger.warning(traceback.format_exc())
        self.remainder += -1
        return sub, ret

    @staticmethod
    def limited_concurrency_coroutines(coros, limit):
        futures = [
            asyncio.ensure_future(c)
            for c in islice(coros, 0, limit)
        ]

        async def first_to_finish():
            while True:
                await asyncio.sleep(0)
                for f in futures:
                    if f.done():
                        futures.remove(f)
                        try:
                            nf = next(coros)
                            futures.append(
                                asyncio.ensure_future(nf))
                        except StopIteration:
                            pass
                        return f.result()

        while len(futures) > 0:
            yield first_to_finish()

    async def start(self, tasks):
        """
        Limit the number of coroutines for reduce memory footprint
        :param tasks:
        :return:
        """
        for res in self.limited_concurrency_coroutines(tasks, self.coroutine_count):
            await res

    @staticmethod
    async def fetch(session, url):
        """
        Fetch url response with session
        :param session:
        :param url:
        :return:
        """
        try:
            async with async_timeout.timeout(10):
                async with session.get(url) as response:
                    return await response.text()
        except Exception as e:
            return None

    async def similarity(self, sub):
        """
        Enumerate subdomains by responding to similarities
        :param sub:
        :return:
        """
        sub_domain = '{sub}.{domain}'.format(sub=sub, domain=self.domain)
        full_domain = 'http://{sub_domain}'.format(sub_domain=sub_domain)
        try:
            resolver = AsyncResolver(nameservers=self.dns_servers)
            conn = aiohttp.TCPConnector(resolver=resolver)
            async with aiohttp.ClientSession(connector=conn, headers=self.request_headers) as session:
                html = await self.fetch(session, full_domain)
                if html is None:
                    return
                if len(html) == self.wildcard_html_len:
                    ratio = 1
                else:
                    # SPEED 4 2 1, but here is still the bottleneck
                    # real_quick_ratio() > quick_ratio() > ratio()
                    ratio = SequenceMatcher(None, html, self.wildcard_html).real_quick_ratio()
                    ratio = round(ratio, 3)
                self.remainder += -1
                if ratio > self.rsc_ratio:
                    logger.debug('{r} RSC ratio: {ratio} (passed) {sub}'.format(r=self.remainder, sub=sub_domain, ratio=ratio))
                else:
                    logger.info('{r} RSC ratio: {ratio} (added) {sub}'.format(r=self.remainder, sub=sub_domain, ratio=ratio))
                    self.wildcard_domains[sub_domain] = html
                    self.data[sub_domain] = self.wildcard_ips
        except Exception as e:
            logger.debug(traceback.format_exc())
            return

    def distinct(self):
        for domain, html in self.wildcard_domains.items():
            for domain2, html2 in self.wildcard_domains.items():
                ratio = SequenceMatcher(None, html, html2).real_quick_ratio()
                if ratio > self.rsc_ratio:
                    # remove this domain
                    if domain2 in self.data:
                        del self.data[domain2]
                    m = 'Remove'
                else:
                    m = 'Stay'
                logger.info('{d} : {d2} {ratio} {m}'.format(d=domain, d2=domain2, ratio=ratio, m=m))

    def run(self):
        """
        Run
        :return:
        """
        start_time = time.time()
        subs = self.load_sub_domain_dict()
        self.remainder = len(subs)
        logger.info('Sub domain dict count: {c}'.format(c=len(subs)))
        logger.info('Generate coroutines...')
        # Verify that all DNS server results are consistent
        stable_dns = []
        wildcard_ips = None
        for dns in self.dns_servers:
            self.resolver = aiodns.DNSResolver(loop=self.loop, nameservers=[dns])
            job = self.query(self.wildcard_sub)
            sub, ret = self.loop.run_until_complete(job)
            logger.info('{dns} {sub} {ips}'.format(dns=dns, sub=sub, ips=ret))
            if ret is None:
                ret = None
            else:
                ret = sorted(ret)
            if dns in self.stable_dns_servers:
                wildcard_ips = ret
            stable_dns.append(ret)
        is_all_stable_dns = stable_dns.count(stable_dns[0]) == len(stable_dns)
        if not is_all_stable_dns:
            logger.info('Is all stable dns: NO, use the default dns server')
            self.resolver = aiodns.DNSResolver(loop=self.loop, nameservers=self.stable_dns_servers)
        # Wildcard domain
        is_wildcard_domain = not (stable_dns.count(None) == len(stable_dns))
        if is_wildcard_domain:
            logger.info('This is a wildcard domain, will enumeration subdomains use by DNS+RSC.')
            self.is_wildcard_domain = True
            if wildcard_ips is not None:
                self.wildcard_ips = wildcard_ips
            else:
                self.wildcard_ips = stable_dns[0]
            logger.info('Wildcard IPS: {ips}'.format(ips=self.wildcard_ips))
            try:
                self.wildcard_html = requests.get('http://{w_sub}.{domain}'.format(w_sub=self.wildcard_sub, domain=self.domain), headers=self.request_headers, timeout=10).text
                self.wildcard_html_len = len(self.wildcard_html)
                logger.debug('Wildcard domain response html length: {len}'.format(len=self.wildcard_html_len))
            except requests.exceptions.ConnectTimeout:
                logger.warning('Request response content failed, check network please!')
        else:
            logger.info('Not a wildcard domain')
        self.coroutine_count = self.coroutine_count_dns
        tasks = (self.query(sub) for sub in subs)
        self.loop.run_until_complete(self.start(tasks))
        dns_time = time.time()
        time_consume_dns = int(dns_time - start_time)

        if self.is_wildcard_domain:
            # Response similarity comparison
            dns_subs = []
            for domain, ips in self.data.items():
                logger.info('{domain} {ips}'.format(domain=domain, ips=ips))
                dns_subs.append(domain.replace('.{0}'.format(self.domain), ''))
            self.wildcard_subs = list(set(subs) - set(dns_subs))
            logger.info('Enumerates {len} sub domains by DNS mode in {tcd}.'.format(len=len(self.data), tcd=str(datetime.timedelta(seconds=time_consume_dns))))
            logger.info('Will continue to test the distinct({len_subs}-{len_exist})={len_remain} domains used by RSC, the speed will be affected.'.format(len_subs=len(subs), len_exist=len(self.data), len_remain=len(self.wildcard_subs)))
            self.coroutine_count = self.coroutine_count_request
            self.remainder = len(self.wildcard_subs)
            tasks = (self.similarity(sub) for sub in self.wildcard_subs)
            self.loop.run_until_complete(self.start(tasks))

            # Distinct last domains use RSC
            # Maybe misinformation
            # self.distinct()

            time_consume_request = int(time.time() - dns_time)
            logger.info('Requests time consume {tcr}'.format(tcr=str(datetime.timedelta(seconds=time_consume_request))))
        # write output
        output_path_with_time = '{pd}/data/{domain}_{time}.esd'.format(pd=self.project_directory, domain=self.domain, time=datetime.datetime.now().strftime("%Y-%m_%d_%H-%M"))
        output_path = '{pd}/data/{domain}.esd'.format(pd=self.project_directory, domain=self.domain)
        max_domain_len = max(map(len, self.data)) + 2
        output_format = '%-{0}s%-s\n'.format(max_domain_len)
        with open(output_path_with_time, 'w') as opt, open(output_path, 'w') as op:
            for domain, ips in self.data.items():
                # The format is consistent with other scanners to ensure that they are
                # invoked at the same time without increasing the cost of resolution
                con = output_format % (domain, ','.join(ips))
                op.write(con)
                opt.write(con)
        logger.info('Output: {op}'.format(op=output_path))
        logger.info('Output with time: {op}'.format(op=output_path_with_time))
        logger.info('Total domain: {td}'.format(td=len(self.data)))
        time_consume = int(time.time() - start_time)
        logger.info('Time consume: {tc}'.format(tc=str(datetime.timedelta(seconds=time_consume))))


if __name__ == '__main__':
    try:
        if len(sys.argv) < 2:
            logger.info("Usage: python ESD.py feei.cn")
            exit(0)
        domains = []
        param = sys.argv[1].strip()
        if os.path.isfile(param):
            with open(param) as fh:
                for line_domain in fh:
                    line_domain = line_domain.strip().lower()
                    re_domain = re.findall(r'^(([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,})$', line_domain)
                    if len(re_domain) > 0 and re_domain[0][0] == line_domain:
                        domains.append(line_domain)
                    else:
                        logger.error('Domain validation failed: {d}'.format(d=line_domain))
        else:
            if ',' in param:
                for p in param.split(','):
                    domains.append(p.strip())
            else:
                domains.append(param)
        logger.info('Total target domains: {ttd}'.format(ttd=len(domains)))
        for d in domains:
            esd = EnumSubDomain(d)
            esd.run()
    except KeyboardInterrupt:
        logger.info('Bye :)')
        exit(0)
