#!/usr/bin/env python

import re
import urllib2
import sys
import argparse
import math
import textwrap


def generate_ovpn(metric):
    results = fetch_ip_data()
    rfile=open('routes.txt','w')
    for ip,mask,_ in results:
        route_item="route %s %s net_gateway %d\n"%(ip,mask,metric)
        rfile.write(route_item)
    rfile.close()
    print "Usage: Append the content of the newly created routes.txt to your openvpn config file," \
          " and also add 'max-routes %d', which takes a line, to the head of the file." % (len(results)+20)


def generate_linux(metric):
    results = fetch_ip_data()
    upscript_header=textwrap.dedent("""\
    #!/bin/sh
    export PATH="/bin:/sbin:/usr/sbin:/usr/bin"

    OLDGW=$(ip route show | grep '^default' | sed -e 's/default via \\([^ ]*\\).*/\\1/')

    if [ "$OLDGW" == '' ]; then
        exit 0
    fi

    if [ ! -e /tmp/vpn_oldgw ]; then
        printf '%s\n' "$OLDGW" > /tmp/vpn_oldgw
    fi

    """)

    downscript_header=textwrap.dedent("""\
    #!/bin/sh
    export PATH="/bin:/sbin:/usr/sbin:/usr/bin"

    OLDGW=$(cat /tmp/vpn_oldgw)

    """)

    upfile=open('ip-pre-up','w')
    downfile=open('ip-down','w')

    upfile.write(upscript_header)
    upfile.write('\n')
    downfile.write(downscript_header)
    downfile.write('\n')

    for ip,mask,_ in results:
        upfile.write('route add -net %s netmask %s gw $OLDGW\n'%(ip,mask))
        downfile.write('route del -net %s netmask %s\n'%(ip,mask))

    downfile.write('rm /tmp/vpn_oldgw\n')


    print "For pptp only, please copy the file ip-pre-up to the folder/etc/ppp," \
          "and copy the file ip-down to the folder /etc/ppp/ip-down.d."

def generate_mac(metric):
    results=fetch_ip_data()

    upscript_header=textwrap.dedent("""\
    #!/bin/sh
    export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
    
    OLDGW=`netstat -nr | grep '^default' | grep -v 'ppp' | sed 's/default *\\([0-9\.]*\\) .*/\\1/' | awk '{if($1){print $1}}'`

    if [ ! -e /tmp/pptp_oldgw ]; then
        printf '%s\n' "$OLDGW" > /tmp/pptp_oldgw
    fi

    dscacheutil -flushcache

    route add 10.0.0.0/8 "${OLDGW}"
    route add 172.16.0.0/12 "${OLDGW}"
    route add 192.168.0.0/16 "${OLDGW}"
    """)

    downscript_header=textwrap.dedent("""\
    #!/bin/sh
    export PATH="/bin:/sbin:/usr/sbin:/usr/bin"

    if [ ! -e /tmp/pptp_oldgw ]; then
            exit 0
    fi

    ODLGW=`cat /tmp/pptp_oldgw`

    route delete 10.0.0.0/8 "${OLDGW}"
    route delete 172.16.0.0/12 "${OLDGW}"
    route delete 192.168.0.0/16 "${OLDGW}"
    """)

    upfile=open('ip-up','w')
    downfile=open('ip-down','w')

    upfile.write(upscript_header)
    upfile.write('\n')
    downfile.write(downscript_header)
    downfile.write('\n')

    for ip,_,mask in results:
        upfile.write('route add %s/%s "${OLDGW}"\n'%(ip,mask))
        downfile.write('route delete %s/%s ${OLDGW}\n'%(ip,mask))

    downfile.write('\n\nrm /tmp/pptp_oldgw\n')
    upfile.close()
    downfile.close()

    print "For pptp on mac only, please copy ip-up and ip-down to the /etc/ppp folder," \
          "don't forget to make them executable with the chmod command."

def generate_win(metric):
    results = fetch_ip_data()

    upscript_header=textwrap.dedent("""@echo off
    for /F "tokens=3" %%* in ('route print ^| findstr "\\<0.0.0.0\\>"') do set "gw=%%*"

    """)

    upfile=open('vpnup.bat','w')
    downfile=open('vpndown.bat','w')

    upfile.write(upscript_header)
    upfile.write('\n')
    upfile.write('ipconfig /flushdns\n\n')

    downfile.write("@echo off")
    downfile.write('\n')

    for ip,mask,_ in results:
        upfile.write('route add %s mask %s %s metric %d\n'%(ip,mask,"%gw%",metric))
        downfile.write('route delete %s\n'%(ip))

    upfile.close()
    downfile.close()

#    up_vbs_wrapper=open('vpnup.vbs','w')
#    up_vbs_wrapper.write('Set objShell = CreateObject("Wscript.shell")\ncall objShell.Run("vpnup.bat",0,FALSE)')
#    up_vbs_wrapper.close()
#    down_vbs_wrapper=open('vpndown.vbs','w')
#    down_vbs_wrapper.write('Set objShell = CreateObject("Wscript.shell")\ncall objShell.Run("vpndown.bat",0,FALSE)')
#    down_vbs_wrapper.close()

    print "For pptp on windows only, run vpnup.bat before dialing to vpn," \
          "and run vpndown.bat after disconnected from the vpn."

def generate_pac(metric):
    results = fetch_ip_data()

    proxy_pac = open("./proxy.pac", "wb")

    proxy_pac.write('PROXY = "SOCKS5 127.0.0.1:1984";\n')
    proxy_pac.write('CHINESE_SUBNETS = [\n')

    for ip, mask, _ in results:
        proxy_pac.write('    ["%s", "%s"],\n' % (ip, mask))
    proxy_pac.write("];\n\n")

    logic = textwrap.dedent("""\
    function inChina(host)
    {
        if (shExpMatch(host, "*.google.*")) {
            return false;
        }

        var ip = dnsResolve(host);
        for (var i = 0; i < CHINESE_SUBNETS.length; i++) {
            var subnet = CHINESE_SUBNETS[i][0];
            var netmask = CHINESE_SUBNETS[i][1];
            if (isInNet(ip, subnet, netmask)) {
                return true;
            }
        }
        return false;
    }

    function FindProxyForURL(url, host)
    {
        if (inChina(host)) {
            return "DIRECT";
        }
        else {
            return PROXY;
        }
    }

    """)

    proxy_pac.write(logic)
    proxy_pac.close()

    print 'The first line of proxy.pac - TYPE "ip:port"'
    print 'TYPE can be PROXY (HTTP), SOCKS (Socks 4), or SOCKS5'
    print 'The default value is PROXY = "SOCKS5 127.0.0.1:1984", PLEASE CHANGE it.'
    print ''
    print "Note: Some browser doesn't support Socks 5 in PAC, although they may support Socks 5 in the settings."
    print 'Tip: You can use "file://path" as the URL of the local file.'

def generate_pydata(metric):
    results = fetch_ip_data()

    pydata = open("./chnroutes_data.py", "wb")

    pydata.write('CHINESE_SUBNETS = [\n')
    for ip, mask, _ in results:
        pydata.write('    ["%s", "%s"],\n' % (ip, mask))
    pydata.write("]\n")
    pydata.close()

def generate_android(metric):
    results = fetch_ip_data()

    upscript_header=textwrap.dedent("""\
    #!/bin/sh
    busybox="$(PATH="/system/xbin/busybox:$PATH" which busybox || echo /system/xbin/busybox)"
    phas(){ type "$@" &>/dev/null; }
    bhas(){ "$busybox" "$@" &>/dev/null; }
    
    phas netstat || alias nestat='"$busybox" netstat'
    phas grep || alias grep='"$busybox" grep'
    phsa route || alias route='"$busybox" route'
    
    read _ OLDGW _ << EOF
    $(netstat -rn | grep ^0\.0\.0\.0)
    EOF
    
    """)

    downscript_header=textwrap.dedent("""\
    busybox="$(PATH="/system/xbin/busybox:$PATH" which busybox || echo /system/xbin/busybox)"
    phas(){ type "$@" &>/dev/null; }
    bhas(){ "$busybox" "$@" &>/dev/null; }
    phas route || alias route='/system/xbin/busybox route'
    
    """)

    upfile=open('vpnup.sh','w')
    downfile=open('vpndown.sh','w')

    upfile.write(upscript_header)
    upfile.write('\n')
    downfile.write(downscript_header)
    downfile.write('\n')

    for ip,mask,_ in results:
        upfile.write('route add -net %s netmask %s gw $OLDGW\n'%(ip,mask))
        downfile.write('route del -net %s netmask %s\n'%(ip,mask))

    upfile.close()
    downfile.close()

    print "Old school way to call up/down script from openvpn client. " \
          "use the regular openvpn 2.1 method to add routes if it's possible"


def fetch_ip_data():
    #fetch data from apnic
    print "Fetching data from apnic.net, it might take a few minutes, please wait..."
    url=r'https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest'
    data=urllib2.urlopen(url).read()

    cnregex=re.compile(r'apnic\|cn\|ipv4\|[0-9\.]+\|[0-9]+\|[0-9]+\|a.*',re.IGNORECASE)
    cndata=cnregex.findall(data)

    results=[]

    for item in cndata:
        unit_items=item.split('|')
        starting_ip=unit_items[3]
        num_ip=int(unit_items[4])

        imask=0xffffffff^(num_ip-1)
        #convert to string
        imask=hex(imask)[2:]
        mask=[0]*4
        mask[0]=imask[0:2]
        mask[1]=imask[2:4]
        mask[2]=imask[4:6]
        mask[3]=imask[6:8]

        #convert str to int
        mask=[ int(i,16 ) for i in mask]
        mask="%d.%d.%d.%d"%tuple(mask)

        #mask in *nix format
        mask2=32-int(math.log(num_ip,2))

        results.append((starting_ip,mask,mask2))

    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description="Generate routing rules for vpn.")
    parser.add_argument('-p','--platform',
                        dest='platform',
                        default='openvpn',
                        nargs='?',
                        help="Target platforms, it can be openvpn, mac, linux,"
                        "win, android and pac. openvpn by default.")
    parser.add_argument('-m','--metric',
                        dest='metric',
                        default=5,
                        nargs='?',
                        type=int,
                        help="Metric setting for the route rules")

    args = parser.parse_args()

    if args.platform.lower() == 'openvpn':
        generate_ovpn(args.metric)
    elif args.platform.lower() == 'linux':
        generate_linux(args.metric)
    elif args.platform.lower() == 'mac' or args.platform.lower() == 'darwin':
        generate_mac(args.metric)
    elif args.platform.lower() == 'win':
        generate_win(args.metric)
    elif args.platform.lower() == 'android':
        generate_android(args.metric)
    elif args.platform.lower() == 'pac':
        generate_pac(args.metric)
    elif args.platform.lower() == "pydata":
        generate_pydata(args.metric)
    else:
        print>>sys.stderr, "Platform %s is not supported."%args.platform
        exit(1)
