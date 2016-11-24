import argparse
import re
import subprocess
import platform
import sys
import os
import threading
import requests

__author__ = "Fabian Landis"
__email__ = "flandis@flandis.com"

"""
Script to select a vpn server to connect to from a list of config files. The
script chooses the server with the lowest latency and lowest server load of
all server or within an area (depending on the command line options). The
following options can be provided to the script via command line or
set in a config file:
config_file: path to a config file - same parameters as command line options
    can be used
selection_metrics: 1) latency, 2) server load, 3) latency, then load
openvpn_path: path to openvpn executable
regex: regex to match dns name to restrict server selection
"""
MAX_LATENCY = 10000
single_matcher = re.compile(" time=(?P<time>\d+(.\d+)?)")
load_matcher = re.compile("<td>(?P<server>\w+\.nordvpn\.com)</td>\S+<td>\S+<div class=\"progress-bar-container\">\S+<span class=\"status_bar\">\S+<span style=\"width: (?P<load>\d+)%")
vpn_domain = 'nordvpn.com'


def choose_server(serverlist, regex=None, metrics='1'):
    myservers = dict()
    loads = None
    if metrics is '1' or metrics is '3': # ping servers
        mythreads = []
        for server in serverlist:
            if regex is None or re.match(regex, server):
                thread = threading.Thread(target=ping, args=(server, 3, myservers))
                mythreads.append(thread)
                thread.start()
        for thread in mythreads:
            thread.join()
        print('Server latencies(ms):')
        print(myservers)
    if metrics is '2' or metrics is '3': # query latency from web page
        loads = server_load(regex)
        print('Server loads(%):')
        print(loads)

    # find best server
    if metrics is '1':
        return min(myservers, key=myservers.get)
    elif metrics is '2':
        return min(loads, key=loads.get)
    else: # optimize latency + load
        print('Ranking of latency and load:')
        ranks = dict()
        for i,el in enumerate(sorted(myservers, key=myservers.get)):
            ranks[el] = i
        for i,el in enumerate(sorted(loads, key=loads.get)):
            ranks[el] += i
        print(ranks)
        return min(ranks, key=ranks.get)


def server_load(regex):
    server_loads = {}
    s = requests.session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:50.0) Gecko/20100101 Firefox/50.0',
               'Accept-Language': 'de,en-US;q=0.7,en;q=0.3',
               'Accept': 'application/json, text/javascript, */*; q=0.01',
               'Accept-Encoding': 'gzip, deflate, br',
               'X-Requested-With': 'XMLHttpRequest',
               'Referer': 'https://nordvpn.com/de/servers/'}
    interesting_countries = ['Australia','Brazil','Canada','Germany','Switzerland','New Zealand','United States']
    for country in interesting_countries:
        payload = {'group': 'Standard VPN servers',
               'country': country,
               'action': 'getGroupRows'}
        x2 = s.get('https://nordvpn.com/wp-admin/admin-ajax.php', params=payload, headers=headers, allow_redirects=True)
        for server in x2.json():
            if regex is None or re.match(regex, str(server['domain'])):
                server_loads[str(server['domain'])] = server['load']
    return server_loads


def ping(host, tries, mydict):
    """
    Returns mean of ping response times
    """

    # Ping parameters as function of OS
    ping_str = '-n' if platform.system().lower() == 'windows' else '-c'

    # Ping
    ping_proc = subprocess.Popen(['ping', ping_str, str(tries), host],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)

    try:
        times = []
        sentinel = b"" if sys.version_info[0] >= 3 else ""
        for line in iter(ping_proc.stdout.readline, sentinel):
            line = line.decode('ascii').strip()
            if not line:
                continue
            match = single_matcher.search(line)
            if match:
                times.append(float(match.group('time')))
                continue
    except KeyboardInterrupt:
        sys.exit()
    if len(times) > 0:
        mydict[host] = sum(times) / float(len(times))
    else:
        mydict[host] = MAX_LATENCY
    return True


if __name__ == '__main__':
    cmdline_parse = argparse.ArgumentParser()
    cmdline_parse.add_argument('-c', '--config_file',
                               help='path to a config file - same parameters as command line option can be used')
    cmdline_parse.add_argument('-s', '--selection_metrics', help='1) latency, 2) server load, 3) latency, then load',
                               default='1',
                               choices=['1', '2', '3'])
    cmdline_parse.add_argument('-o', '--openvpn_path', help='path to openvpn executable')
    cmdline_parse.add_argument('-p', '--path_files', help='path to openvpn config files used to get server names',
                               required=True)
    cmdline_parse.add_argument('-r', '--regex', help='regex to match dns name to restrict server selection')
    cmdline_parse.add_argument('-v', '--verbose', help='print additional informations', default=False,
                               action='store_true')
    cmdline_parse.add_argument('-u', '--udp', help='use udp instead of tcp',action="store_true")

    arg = cmdline_parse.parse_args()

    if arg.config_file:
        c = open(arg.config_file, 'r+')

    # TODO: Unpack config parameters from config file
    # TODO: Implement other metrics besides latency

    tryservers = set()
    fname_matcher = re.compile('(?P<dns>\w+\.' + vpn_domain + ')\.(?P<protocol>\w+\d+)\.ovpn')
    if arg.path_files:
        for f in os.listdir(arg.path_files):
            if os.path.isfile(os.path.join(arg.path_files, f)):
                match = fname_matcher.search(f)
                if match:
                    tryservers.add(match.group('dns'))

    chosen_server = choose_server(serverlist=tryservers, regex=arg.regex, metrics=arg.selection_metrics )
    print('Fastest server in area: ' + chosen_server)

    if arg.udp:
        suffix = '.udp1194.ovpn'
    else:
        suffix = '.tcp443.ovpn'


    if platform.system().lower() == 'windows':
        cmd = 'openvpn-gui --connect ' + chosen_server + suffix
    else:
        cmd = 'openvpn '+ os.path.join(arg.path_files, chosen_server) + suffix
    subprocess.call(cmd , shell=True)
