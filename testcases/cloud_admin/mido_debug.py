from midonetclient.api import MidonetApi
from midonetclient.router import Router
from midonetclient import resource_base
from midonetclient import vendor_media_type
from midonetclient.bridge import Bridge
from midonetclient.ip_addr_group import IpAddrGroup
from eucaops import Eucaops
from eutester import WaitForResultException
from eutester.sshconnection import SshConnection
from eutester.euinstance import EuInstance
from eutester.eulogger import Eulogger
from boto.ec2.instance import Instance
from prettytable import PrettyTable
import requests
import socket
import re
import copy

class ArpTable(resource_base.ResourceBase):
    def __init__(self, uri, dto, auth):
        super(ArpTable, self).__init__(uri, dto, auth)

    def get_ip(self):
        return self.dto.get('ip')

    def get_mac(self):
        return self.dto.get('mac')

    def get_macaddr(self):
        return self.dto.get('macAddr')

class MacTable(resource_base.ResourceBase):
    def __init__(self, uri, dto, auth):
        super(MacTable, self).__init__(uri, dto, auth)

    def get_port_id(self):
        return self.dto.get('portId')

    def get_bridge_id(self):
        return self.dto.get('bridgeId')

    def get_vlan_id(self):
        return self.dto.get('vlanId')

    def get_macaddr(self):
        return self.dto.get('macAddr')


class MidoDebug(object):
    _chain_jump = 107

    def __init__(self, midonet_api_host, midonet_api_port='8080', midonet_username=None,
                 midonet_password=None, eutester_config=None, eutester_password=None, tester=None):
        self.midonet_api_host = midonet_api_host
        self.midonet_api_port = midonet_api_port
        self.midonet_username = midonet_username
        self.midonet_password = midonet_password
        self.mapi = MidonetApi(base_uri='http://{0}:{1}/midonet-api'
                          .format(self.midonet_api_host, self.midonet_api_port),
                          username=self.midonet_username, password=self.midonet_password)

        self.tester = tester
        if not self.tester:
            self.tester = Eucaops(config_file=eutester_config, password=eutester_password)
        self.logger = Eulogger(identifier='MidoDebug:{0}'.format(self.midonet_api_host))
        self.default_indent = "  "
        self._protocols = {}

    def debug(self, msg):
        self.logger.log.debug(msg)

    def _indent_table_buf(self, table, indent=None):
        if indent is None:
            indent = self.default_indent
        buf = str(table)
        ret_buf = ""
        for line in buf.splitlines():
                ret_buf += '{0}{1}\n'.format(indent,line)
        return ret_buf

    def _link_table_buf(self, table, indent=3):
        if not table:
            return None
        if indent < 2:
            indent = 2
        preline = ""
        linkpoint = ""
        linkline = "{0}\n".format(self._bold("|", 103))
        for x in xrange(0,indent-1):
            linkpoint += "-"
        for x in xrange(0, indent+1):
            preline += " "
        linkline += self._bold("+{0}>".format(linkpoint), 103)
        lines = str(table).splitlines()
        ret_buf = "{0}{1}\n".format(linkline, lines[0])
        for line in lines[1:]:
            ret_buf += '{0}{1}\n'.format(preline,line)
        return ret_buf

    def _header(self, text):
        return "\033[94m\033[1m{0}\033[0m".format(text)

    def _bold(self, text, value=1):
        buf = ""
        lines = []
        for line in text.splitlines():
            lines.append("\033[1;{0}m{1}\033[0m".format(value, line))
        buf = "\n".join(lines)
        if text.endswith('\n') and not buf.endswith('\n'):
            buf += '\n'
        return buf

    def _highlight_buf_for_instance(self, buf, instance):
        ret_buf = ""
        for line in str(buf).splitlines():
            searchstring= "{0}|{1}|{2}".format(instance.id,
                                               instance.private_ip_address,
                                               instance.ip_address)
            try:
                searchstring = "{0}|{1}".format(
                    searchstring,
                    self.tester.ec2.get_all_subnets(instance.subnet_id)[0].cidr_block)
            except:pass
            for match in re.findall(searchstring,line):
                line = line.replace(match, self._bold(match, 102))
            ret_buf += line + "\n"
        return ret_buf

    @property
    def protocols(self):
        if not self._protocols:
            proto_dict = {}
            for attr in dir(socket):
                if attr.startswith('IPPROTO_'):
                          proto_dict[str(getattr(socket, attr))]  = attr.replace('IPPROTO_','').upper()
            self._protocols = proto_dict
        return self._protocols

    def _get_protocol_name_by_number(self, number):
        #look up protocol by number, return protocol name or just give the number back
        return self.protocols.get(str(number), str(number))


    def _get_instance(self, instance):
        if not isinstance(instance, Instance):
            if isinstance(instance, str):
                fetched_ins = self.tester.get_instances(idstring=['verbose', instance])
            if not fetched_ins:
                raise ValueError('Could not find instance {0} on system'.format(instance))
            instance = fetched_ins[0]
        return instance

    def _ping_instance_private_ip_from_euca_internal(self,
                                                     instance,
                                                     proxy_machine,
                                                     net_namespace=None):
        instance = self._get_instance(instance)
        try:
            proxy_machine.machine.ping_check(instance.private_ip_address,
                                             net_namespace=net_namespace)
            return True
        except Exception, PE:
            self.debug('Ping Exception:{0}'.format(PE))
            self.debug('Failed to ping instance: {0},  private ip:{1} from internal host: {2}'
                          .format(instance.id,
                                  instance.private_ip_address,
                                  proxy_machine.hostname))
        return False

    def ping_instance_private_ip_from_euca_internal(self,
                                                    instance,
                                                    proxy_machine=None,
                                                    net_namespace=None,
                                                    ping_timeout=5):
        instance = self._get_instance(instance)
        if not proxy_machine:
            clc_service = self.tester.service_manager.get_all_cloud_controllers()[0]
            proxy_machine = copy.copy(clc_service)
        net_namespace = net_namespace or instance.vpc_id
        try:
            self.tester.wait_for_result(self._ping_instance_private_ip_from_euca_internal,
                                        result=True,
                                        timeout=ping_timeout,
                                        instance=instance,
                                        proxy_machine=proxy_machine,
                                        net_namespace=net_namespace)
        except WaitForResultException:
            self.errormsg('Failed to ping instance: {0},  private ip:{1} from internal host: {2}'
                          .format(instance.id,
                                  instance.private_ip_address,
                                  proxy_machine.hostname))
            self.errormsg('Ping failure. Fetching network debug info from internal host...')
            proxy_machine.machine.dump_netfail_info(ip=instance.private_ip_address,
                                            net_namespace=net_namespace)
            self.errormsg('Done fetching/logging network debug info from internal euca proxy host'
                          'used in ping attempt to instance {0}, private ip: {1}, from '
                          'internal host: {2}'.format(instance.id,
                                                      instance.private_ip_address,
                                                      proxy_machine.hostname))
            raise
        self.debug('Successfully pinged instance: {0},  private ip:{1} from internal host: {2}'
                   .format(instance.id,
                           instance.private_ip_address,
                           proxy_machine.hostname))


    def get_all_routers(self, search_dict={}, eval_op=re.search, query=None):
        """
        Returns all routers that have attributes and attribute values as defined in 'search_dict'
        """
        routers = self.mapi.get_routers(query=None)
        remove_list = []
        for key in search_dict:
            for router in routers:
                if hasattr(router, key):
                    try:
                        if eval_op(str(search_dict[key]), router.dto.get(key)) :
                            continue
                    except:
                        self.debug('Error while evaluating -> {0}("{1}","{2}")'
                               .format("{0}.{1}".format(getattr(eval_op, "__module__",""),
                                                        getattr(eval_op, "__name__","")),
                                       str(search_dict[key]),
                                       str(getattr(router,key))))
                        raise
                remove_list.append(router)
            for router in remove_list:
                if router in routers:
                    routers.remove(router)
        return routers

    def get_router_for_instance(self,instance):
        instance = self._get_instance(instance)
        self.debug('Getting router for instance:{0}, vpc:{1}'.format(instance.id,  instance.vpc_id))
        routers = self.get_all_routers(search_dict={'name':instance.vpc_id})
        if len(routers) != 1:
            raise ValueError('Expected to find 1 matching router for instance:{0}, found:{1}'
                             .format(instance.id, routers))
        router = routers[0]
        self.debug('Found router:{0} for instance:{1}'.format(router.get_name(), instance.id))
        return router

    def get_router_by_name(self, name):
        assert name
        search_string = "^{0}$".format(name)
        self.debug('search string:{0}'.format(search_string))
        routers =  self.get_all_routers(search_dict={'name':search_string}, eval_op=re.match)
        if routers:
            return routers[0]
        return None


    def show_routers_brief(self, routers=None, printme=True):
        """
        Show a list of of routers, or by default all routers available in the current session
        context. Use show_routers to display the route information of each router.
        """
        if routers is None:
            routers = self.get_all_routers()
        if not isinstance(routers,list):
            routers = [routers]
        pt = PrettyTable(['Name', 'AdminState', 'ID', 'InboundChain', 'OutboundChain','T-ID' ])
        for router in routers:
            pt.add_row([router.get_name(),router.get_admin_state_up(), router.get_id(),
                        router.get_inbound_filter_id(),router.get_outbound_filter_id(),
                        router.get_tenant_id()])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt

    def show_routes(self, routes, printme=True):
        '''
        show a list of provided route objects
        '''
        if not isinstance(routes,list):
            routes = [routes]
        pt = PrettyTable(['Destination','Source', 'nexthopGW', 'nexthop', 'weight', 'ID'])
        for route in routes:
            pt.add_row(['{0}/{1}'.format(route.get_dst_network_addr(),
                                         route.get_dst_network_length()),
                        '{0}/{1}'.format(route.get_src_network_addr(),
                                         route.get_src_network_length()),
                        route.get_next_hop_gateway(),
                        route.get_next_hop_port(),
                        route.get_weight(),
                        route.get_id()
                        ])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt

    def show_routers(self, routers=None, printme=True):
        '''
        Show a list of routers, or by default all routers in the current session context
        '''
        buf = ""
        if routers is None:
            routers = self.get_all_routers()
        if not isinstance(routers,list):
            routers = [routers]
        for router in routers:
            buf += str(self.show_router_summary(router, showchains=False, printme=False)) + "\n"
        self.debug(buf)


    def show_router_summary(self, router, showchains=True, indent=None, printme=True):
        """
        Show a single routers summary
        """
        if indent is None:
            indent = self.default_indent
        title = self._header("ROUTER:{0}".format(router.get_name()))
        pt = PrettyTable([title])
        pt.align[title] = 'l'
        buf = self._bold("{0}ROUTER SUMMARY:\n".format(indent), 4)
        buf += self._indent_table_buf(self.show_routers_brief(routers=[router], printme=False))
        buf += self._bold("{0}ROUTES:\n".format(indent), 4)
        buf += self._indent_table_buf(self.show_routes(routes=router.get_routes(), printme=False))
        buf += self._bold("{0}ROUTER PORTS:\n".format(indent), 4)
        buf += self._indent_table_buf(self.show_ports(ports=router.get_ports(), printme=False))
        if showchains:
            if router.get_inbound_filter_id():
                in_filter = self.mapi.get_chain(str(router.get_inbound_filter_id()))
                buf += self._bold("{0}ROUTER INBOUND FILTER:\n".format(indent), 4)
                buf += self._indent_table_buf(self.show_chain(chain=in_filter, printme=False))
            if router.get_outbound_filter_id():
                out_filter = self.mapi.get_chain(str(router.get_outbound_filter_id()))
                buf += self._bold("{0}ROUTER OUTBOUND FILTER:\n".format(indent), 4)
                buf += self._indent_table_buf(self.show_chain(chain=out_filter, printme=False))
        pt.add_row([buf])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt

    def get_device_by_peer_id(self, peerid):
        device = None
        port = self.mapi.get_port(peerid)
        type = str(port.get_type()).upper()
        if type == 'BRIDGE':
            device = self.mapi.get_bridge(port.get_device_id())
        if type == 'ROUTER':
            device = self.map.get_router(port.get_device_id())
        if not device:
            raise ValueError('Unknown device type for peerid:{0}, port:{1}, type:{2}'
                             .format(peerid, port.get_id(), port.get_type()) )
        return device


    def get_router_port_for_subnet(self, router, cidr):
        assert cidr
        for port in router.get_ports():
            network = "{0}/{1}".format(port.get_network_address(), port.get_network_length())
            if str(network) == str(cidr):
                return port
        return None


    def get_bridge_for_instance(self, instance):
        instance = self._get_instance(instance)
        router = self.get_router_for_instance(instance)
        if not router:
            raise ValueError('Did not find router for instance:{0}'.format(instance.id))
        subnet = self.tester.ec2.get_all_subnets(subnet_ids=['verbose', instance.subnet_id])[0]
        if not subnet:
            raise ValueError('Did not find subnet for instance:{0}, subnet id:{1}'
                             .format(instance.id, instance.subnet_id))
        port = self.get_router_port_for_subnet(router, subnet.cidr_block)
        if not port:
            raise ValueError('Did not find router port for instance:{0}, subnet:{1}'
                                .format(instance.id, subnet.cidr_block))
        bridge = self.get_device_by_peer_id(port.get_peer_id())
        if not isinstance(bridge, Bridge):
            raise ValueError('peer device for instance router is not a bridge, '
                             'fix the topo assumptions made in this method!')
        return bridge

    def show_port_summary(self, port, showchains=True, showbgp=True, indent=None, printme=True):
        if indent is None:
            indent = self.default_indent
        title = self._bold("PORT SUMMARY FOR PORT:{0}".format(port.get_id()), 94)
        titlept = PrettyTable([title])
        titlept.align[title] = 'l'
        buf = self._bold("{0}PORT INFO:\n".format(indent), 4)
        pt = PrettyTable(['PORT ID', 'BGPS', 'IPADDR', 'NETWORK', 'MAC',
                              'TYPE', 'UP', 'PEER ID'])
        bgps = 0
        try:
            if port.dto.get('bgps'):
                bgps =  port.get_bgps()
                if bgps:
                    bgps = len(bgps)
                else:
                    bgps = 0
        except Exception, E:
            bgps = 'ERROR'
            self.debug('Error fetching bgps from port:{0}, err"{1}'.format(port.get_id(), E))

        pt.add_row([port.get_id(),
                    bgps,
                    port.get_port_address(),
                    "{0}/{1}".format(port.get_network_address(), port.get_network_length()),
                    port.get_port_mac(),
                    port.get_type(),
                    port.get_admin_state_up(),
                    port.get_peer_id()])
        buf += self._indent_table_buf(str(pt))
        if showbgp and bgps:
            buf += self._bold("{0}PORT BGP INFO:\n".format(indent), 4)
            buf += self._indent_table_buf(str(self.show_bgps(port.get_bgps() or [] )))
        if showchains:
            if port.get_inbound_filter_id():
                in_filter = self.mapi.get_chain(str(port.get_inbound_filter_id()))
                buf += self._bold("{0}PORT INBOUND FILTER:".format(indent), 4)
                buf += "\n"
                buf += self._indent_table_buf(self.show_chain(chain=in_filter, printme=False))
            if port.get_outbound_filter_id():
                out_filter = self.mapi.get_chain(str(port.get_outbound_filter_id()))
                buf += self._bold("{0}PORT OUTBOUND FILTER:".format(indent), 4)
                buf += "\n"
                buf += self._indent_table_buf(self.show_chain(chain=out_filter, printme=False))
        titlept.add_row([buf])
        if printme:
            self.debug('\n{0}\n'.format(titlept))
        else:
            return titlept

    def show_ports(self, ports, showchains=False,   printme=True):
        """
        Show formatted info about a specific port
        """
        buf = ""
        if not isinstance(ports,list):
            ports = [ports]
        pt = None
        for port in ports:

            pt = PrettyTable(['PORT ID', 'BGPS', 'IPADDR', 'NETWORK', 'MAC',
                              'TYPE', 'UP', 'PEER ID'])
            bgps = 0
            try:
                if port.dto.get('bgps'):
                    bgps =  port.get_bgps()
                    if bgps:
                        bgps = len(bgps)
                    else:
                        bgps = 0
            except Exception, E:
                bgps = 'ERROR'
                self.debug('Error fetching bgps from port:{0}, err"{1}'.format(port.get_id(), E))


            pt.add_row([port.get_id(),
                        bgps,
                        port.get_port_address(),
                        "{0}/{1}".format(port.get_network_address(), port.get_network_length()),
                        port.get_port_mac(),
                        port.get_type(),
                        port.get_admin_state_up(),
                        port.get_peer_id()])

            if bgps and bgps != "ERROR":
                lines = []
                for line in str(pt).splitlines():
                    line = line.strip()
                    if line:
                        lines.append(line)
                footer = lines[-1]
                buf += "\n".join(lines) + '\n'
                pt = None
                buf += self._link_table_buf(self.show_bgps(port.get_bgps(), printme=False))
                buf += footer +'\n'

        if pt:
            buf += str(pt)
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return buf


    def show_bgps(self, bgps, printme=True):
        buf = ""
        if not isinstance(bgps,list):
            bgps = [bgps]
        port=None
        pt=None
        for bgp in bgps:
            if bgp.dto.get('portId') != port:
                port = bgp.dto.get('portId')
                if pt is not None:
                    buf += str(pt)
                port_header = 'BGP INFO FOR PORT:'.format(port)
                pt = PrettyTable([port_header, 'BGP ID', 'PEER ADDR',
                                  'LOCAL AS', 'PEER AS', 'AD ROUTES'])
                pt.max_width[port_header] = len(port) or len('BGP INFO FOR PORT:')
                pt.align[port_header] = 'l'
            pt.add_row([port,
                        bgp.get_id(),
                        bgp.get_peer_addr(),
                        bgp.get_local_as(),
                        bgp.get_peer_as(),
                        self._format_ad_routes(bgp.get_ad_routes())])
        buf += str(pt)
        if printme:
            self.debug('\n{0}\n'.format(buf))
        else:
            return buf


    def _format_ad_routes(self, ad_routes):
        adrs =[]
        if not isinstance(ad_routes,list):
            ad_routes = [ad_routes]
        for adr in ad_routes:
            adrs.append('{0}/{1}'.format(adr.get_nw_prefix(), adr.get_prefix_length()))
        return adrs



    def show_bridges(self, bridges=None, indent=None, printme=True):
        if indent is None:
            indent = self.default_indent
        if bridges:
            if not isinstance(bridges,list):
                bridges = [bridges]
        else:
            bridges = self.mapi.get_bridges(query=None)
        printbuf = ""
        for bridge in bridges:
            buf = ""
            pt = PrettyTable(['BRIDGE NAME', 'ID', 'TENANT', 'Vx LAN PORT'])
            pt.add_row([bridge.get_name(), bridge.get_id(), bridge.get_tenant_id(),
                       bridge.get_vxlan_port()])
            title = self._header('BRIDGE:"{0}"'.format(bridge.get_name()))
            box = PrettyTable([title])
            box.align[title] = 'l'
            buf += self._bold("{0}BRIDGE SUMMARY:\n".format(indent), 4)
            buf += self._indent_table_buf(str(pt))
            buf += self._bold("{0}BRIDGE PORTS:\n".format(indent), 4)
            buf += self._indent_table_buf(self.show_ports(bridge.get_ports(), printme=False), 4)
            buf += self._bold("{0}BRIDGE ARP TABLE:\n".format(indent), 4)
            buf += self._indent_table_buf(self.show_bridge_arp_table(bridge=bridge, printme=False)
                                          , 4)
            buf += self._bold("{0}BRIDGE DHCP SUBNETS:\n".format(indent))
            buf += self._indent_table_buf(self.show_bridge_dhcp_subnets(bridge, printme=False), 4)
            buf += self._bold("{0}BRIDGE MAC TABLE:\n".format(indent))
            buf += self._indent_table_buf(self.show_bridge_mac_table(bridge=bridge, printme=False),
                                          4)
            box.add_row([buf])
            printbuf += str(box) + "\n"
        if printme:
            self.debug('\n{0}\n'.format(printbuf))
        else:
            return printbuf

    def show_bridge_dhcp_subnets(self, bridge, printme=True):
        pt = PrettyTable(['SUBNET', 'SERVER ADDR', 'DefaultGW', 'DNS SERVERS', 'STATE'])
        for subnet in bridge.get_dhcp_subnets():
            pt.add_row(["{0}/{1}".format(subnet.get_subnet_prefix(), subnet.get_subnet_length()),
                       subnet.get_server_addr(),
                       subnet.get_default_gateway(),
                       ",".join(str(dns) for dns in subnet.get_dns_server_addrs()),
                       subnet.dto.get('enabled')])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt


    def get_bridge_arp_table(self, bridge):
        table = bridge.get_children(bridge.dto['arpTable'],
                                    query=None,
                                    headers={"Accept":""},
                                    clazz=ArpTable)
        return table

    def get_bridge_mac_table(self, bridge):
        table = bridge.get_children(bridge.dto['macTable'],
                                    query=None,
                                    headers={"Accept":""},
                                    clazz=MacTable)
        return table

    def show_bridge_mac_table(self, bridge, printme=True):
        pt=PrettyTable(['BRIDGE ID', 'MAC ADDR', 'PORT ID', 'VLAN ID'])
        mac_table = self.get_bridge_mac_table(bridge)
        for entry in mac_table:
            assert  isinstance(entry, MacTable)
            pt.add_row([entry.get_bridge_id(), entry.get_macaddr(), entry.get_port_id(),
                        entry.get_vlan_id()])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt

    def show_bridge_arp_table(self, bridge, printme=True):
        pt = PrettyTable(['IP', 'MAC', 'MAC ADDR', 'VM ID', 'NC', 'LEARNED PORT'])
        table = self.get_bridge_arp_table(bridge)
        mac_table = self.get_bridge_mac_table(bridge)
        for entry in table:
            instance_id = None
            vm_host = None
            entry_ip = entry.get_ip()
            port = "NOT LEARNED"
            for mac in mac_table:
                if mac.get_macaddr() == entry.get_mac():
                    port = mac.get_port_id()
            if self.tester:
                try:
                    euca_instance = self.tester.get_instances(
                        idstring=['verbose'],
                        filters={'network-interface.addresses.private-ip-address':entry_ip})
                    #euca_instance = self.tester.get_instances(instance_id=['verbose'], privip=entry_ip)
                    if euca_instance:
                        euca_instance = euca_instance[0]
                        instance_id = self._bold(euca_instance.id)
                        vm_host = euca_instance.tags.get('euca:node',None)
                except:
                    raise
            pt.add_row([entry_ip, entry.get_mac(), entry.get_macaddr(), instance_id, vm_host, port])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt

    def get_bridge_port_for_instance(self, instance):
        bridge = self.get_bridge_for_instance(instance)
        arp_table = self.get_bridge_arp_table(bridge)
        mac_table = self.get_bridge_mac_table(bridge)
        arp_entry = None
        for a_entry in arp_table:
            if a_entry.get_ip() == instance.private_ip_address:
                arp_entry = a_entry
                break
        if arp_entry:
            for m_entry in mac_table:
                if m_entry.get_macaddr() == arp_entry.get_mac():
                    portid = m_entry.get_port_id()
                    return self.mapi.get_port(portid)
            self.debug('ARP entry for instance found, but mac has not been learned on a port yet, try pinging it?   ')
        return None

    def show_bridge_port_for_instance(self, instance, showchains=True, indent=None, printme=True):

        def not_learned_warning():
            wbuf = ""
            wbuf += self._indent_table_buf(self._bold("MAC IS NOT LEARNED ON A BRIDGE PORT AT "
                                                     "THIS TIME !?!", 91))
            wbuf += "\n"
            wbuf += self._indent_table_buf(self._bold("(try pinging the addr?)", 91))
            wbuf += "\n"
            return wbuf
        if indent is None:
            indent = self.default_indent
        bridge = self.get_bridge_for_instance(instance)
        title = self._bold('BRIDGE PORT FOR INSTANCE:{0}, (BRIDGE:{1})'.format(instance.id,
                                                                               bridge.get_name() or
                                                                               bridge.get_id()), 94)
        pt = PrettyTable([title])
        pt.align[title] ='l'
        buf = ""
        port = self.get_bridge_port_for_instance(instance)
        if not port:
            # Port may not be currently active/learned on the bridge,
            # try to ping the private interface...
            try:
                self.debug(self._bold("MAC IS NOT LEARNED ON A BRIDGE PORT AT THIS TIME !?!", 91))
                self.debug(self._bold("Trying to ping the instance private addr('{0}') now...?)"
                                      .format(instance.private_ip_address), 91))
                self.ping_instance_private_ip_from_euca_internal(instance)
            except WaitForResultException:pass
            port = self.get_bridge_port_for_instance(instance)
        if port:
            buf += self._indent_table_buf(str(self.show_port_summary(port, showchains=showchains,
                                              printme=False)))
            '''
            buf += self._bold("{0}PORT SUMMARY:\n".format(indent))
            buf += self._indent_table_buf(str(self.show_ports(ports=[port], printme=False)))
            if showchains:
                if port.get_inbound_filter_id():
                    in_filter = self.mapi.get_chain(str(port.get_inbound_filter_id()))
                    buf += self._bold("{0}PORT INBOUND FILTER:".format(indent), 46)
                    buf += "\n"
                    buf += self._indent_table_buf(self.show_chain(chain=in_filter, printme=False))
                if port.get_outbound_filter_id():
                    out_filter = self.mapi.get_chain(str(port.get_outbound_filter_id()))
                    buf += self._bold("{0}PORT OUTBOUND FILTER:".format(indent), 46)
                    buf += "\n"
                    buf += self._indent_table_buf(self.show_chain(chain=out_filter, printme=False))
            '''
        else:
            buf += self._indent_table_buf(self._bold("MAC IS NOT LEARNED ON A BRIDGE PORT AT "
                                                     "THIS TIME !?!", 91))
            buf += "\n"
            buf += self._indent_table_buf(self._bold("(try pinging the addr?)", 91))
            buf += "\n"
        pt.add_row([buf])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt


    def show_chain(self, chain, printme=True):
        title = 'CHAIN NAME: {0}, TENANT ID:{1}'.format(self._bold(chain.get_id(), self._chain_jump),
                                                        chain.dto.get('tenantId', ""))
        pt = PrettyTable([title])
        pt.align[title] = 'l'
        rules = chain.get_rules()
        if not rules:
            pt.add_row(['NO RULES'])
        else:
            rulesbuf = str(self.show_rules(rules=chain.get_rules(), jump=True, printme=False))
            pt.add_row([rulesbuf])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt

    def show_rules(self, rules, jump=False, printme=True):
        '''
            midonet> chain ec8b6a76-63b0-4952-89de-33b62da492e7 list rule
            rule rule0 dst !172.31.0.2 proto 0 tos 0 ip-address-group-src ip-address-group1
            fragment-policy any pos 1 type snat action continue target 10.116.169.162

            dst $nwDstAddress/$nwDstLength  proto $nwProto tos $nwTos
            ip-address-group-src $ipAddrGroupSrc fragment-policy $fragmentPolicy pos $position
            type $type action $natFlowAction target $natTargets
        '''
        if not isinstance(rules, list):
            rules = [rules]
        buf = ""
        pt = None
        for rule in rules:
            if pt is None:
                chain_id = rule.get_chain_id()
                #title = "RULE(S) FOR CHAIN: {1}".format(rules.index(rule),chain_id)

                title = "RULE(S) for CHAIN: {0}".format("{0}..{1}{2}".format(chain_id[0:5],
                                                                             chain_id[-5:-1],
                                                                             chain_id[-1]))
                pt = PrettyTable([title, 'DST', 'PROTO', 'DSTPORTS', 'TOS', 'IP GRP ADDRS','FRAG POL',
                                  'POS', 'TYPE', 'ACTION', 'TARGET'])
            jump_chain = None
            action = rule.dto.get('flowAction', "")
            targets = []
            nattargets = rule.dto.get('natTargets') or []
            ports = None
            tpdst = rule.dto.get('tpDst', None)
            if tpdst:
                ports = "{0}:{1}".format(tpdst.get('start',""), tpdst.get('end', ""))
            rule_type = self._bold(rule.get_type())
            for nattarget in nattargets:
                targets.append(nattarget.get('addressFrom'))
            targetstring = self._bold(",".join(targets))
            if rule.get_type().upper() == 'JUMP':
                jump_chain_id = rule.get_jump_chain_id()
                jump_chain = self.mapi.get_chain(jump_chain_id)
                rule_type = self._bold(rule.get_type(), self._chain_jump)
                action = self._bold('to chain', self._chain_jump)
                targetstring = self._bold(jump_chain_id, self._chain_jump)
            ip_addr_group = rule.get_ip_addr_group_src()
            if ip_addr_group:
                ip_addr_group = self.show_ip_addr_group_addrs(ipgroup=ip_addr_group, printme=False)
            pt.add_row(['RULE#{0}:{1}'.format(rules.index(rule)+1,rule.get_id()),
                        "{0}/{1}".format(rule.get_nw_dst_address(), rule.get_nw_dst_length()),
                        self._get_protocol_name_by_number(rule.get_nw_proto()),
                        ports,
                        rule.get_nw_tos(),
                        ip_addr_group,
                        rule.get_fragment_policy(),
                        rule.get_position(),
                        rule_type,
                        action,
                        targetstring])
            if jump_chain and jump:
                buf += str(pt) + "\n"
                pt = None
                #buf += "|\n" + "+->\n"
                #buf += str(self.show_chain(jump_chain, printme=False)) + "\n"
                buf += self._link_table_buf(self.show_chain(jump_chain, printme=False))
        buf += str(pt)
        if printme:
            self.debug('\n{0}\n'.format(buf))
        else:
            return buf

    def show_router_for_instance(self,instance, printme=True):
        ret_buf = self._highlight_buf_for_instance(
            buf=self.show_router_summary(router=self.get_router_for_instance(instance=instance),
                                         printme=False),
            instance=instance)
        if printme:
            self.debug('\n{0}\n'.format(ret_buf))
            return None
        else:
            return ret_buf



    def show_bridge_for_instance(self, instance, printme=True):
        ret_buf = self._highlight_buf_for_instance(
            buf=self.show_bridges(bridges=self.get_bridge_for_instance(instance=instance),
                                  printme=False),
            instance=instance)
        if printme:
            self.debug('\n{0}\n'.format(ret_buf))
            return None
        else:
            return ret_buf

    def show_instance_network_summary(self, instance, printme=True):
        instance = self._get_instance(instance)
        self.debug('Gathering network info... (this may take a few seconds)')
        title = ("NETWORK SUMMARY FOR INSTANCE:{0}, (PRIVIP:{1}, PUBIP:{2})"
                 .format(instance.id, instance.private_ip_address, instance.ip_address))
        pt = PrettyTable([title])
        pt.align[title] = 'l'
        buf = str(self.show_router_for_instance(instance=instance, printme=False))
        buf += str(self.show_bridge_for_instance(instance=instance, printme=False))
        buf += str(self.show_bridge_port_for_instance(instance=instance, printme=False))
        buf += "\n"
        eucatitle = self._bold('"EUCALYPTUS CLOUD" INSTANCE INFO ({0}):'.format(instance.id), 94)
        ept = PrettyTable([eucatitle])
        ept.align[eucatitle] = 'l'
        ebuf = "\n" + str(self.tester.print_euinstance_list([instance], printme=False)) + "\n"
        ebuf += str(self.show_security_groups_for_instance(instance=instance, printme=False))
        ept.add_row([ebuf])
        buf += str(ept)
        pt.add_row([buf])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt


    def show_security_groups_for_instance(self, instance, printme=True):
        buf = ""
        instance = self._get_instance(instance)
        title = self._bold("EUCA SECURITY GROUPS FOR INSTANCE:{0}".format(instance.id))
        pt = PrettyTable([title])
        pt.align['title'] = 'l'
        for group in instance.groups:
            buf += str(self.tester.show_security_group(group=group, printme=False))
        pt.add_row([buf])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        else:
            return pt


    def show_ip_addr_group_addrs(self, ipgroup, printme=True):
        if not isinstance(ipgroup, IpAddrGroup):
            ipgroup = self.mapi.get_ip_addr_group(ipgroup)
        if not ipgroup:
            raise ValueError('ipgroup not found or populated for show_ip_addr_group_addrs')
        addrs = []
        grpaddrs = ipgroup.get_addrs()
        for ga in grpaddrs:
            addr = ga.get_addr()
            if addr:
                addrs.append(str(addr))
        ret_buf = ",".join(addrs)
        if printme:
            self.debug('\n{0}\n'.format(ret_buf))
        else:
            return ret_buf



