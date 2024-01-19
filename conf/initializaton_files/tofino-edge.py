#
# Your goal is to put the correct configuration into this script, so that
# you can run the LAG  PTF test
#
# ./run_p4_tests.sh -p simple_l3_lag_ecmp                           \
#                   -t ~/labs/09-simple_l3_lag_ecmp/ptf-tests       \
#                   [--test-param="param_1=val1;param_2=val2;..."]  \
#                   [-s test.<test_name>]
#
# and it will pass.
#
# Available test names are:
#  LagIPv{4,6}Seq     -- These tests send IPv4/IPv6 TCP packets, while
#                        incrementing both SIP, DIP and TCP src/dst ports
#                        in each packet
#  LagIPv{4,6}4Random -- These tests send IPv4/IPv6 packets, randomly choosing
#                        SIP, DIP, protocol (TCP or UDP) as well as Layer 4
#                        source/destination port for each packet
#
# You can control the number of packets being sent by adding a test parameter
# pkt_count. For example:
#        --test-param="pkt_count=10"
#
# More parameters are described in the Lab Guide
#
# Watch out for the proper placement of quotation marks and apostrophes!
#
# In this case the test will send 30 packets (presumably 10 for each of the
# 3 ports  in the lag).

#
# This module will help you with IPv4 and Ethernet MAC addresses
#
# Ethernet: EUI('00:11:22:33:44:55')
# IPv4 :    IPAddress('192.168.1.254')
#
# And you can pass them as arguments when constructing table entries
from netaddr import EUI, IPAddress

p4 = bfrt.tenant_inc.pipe

#####
# Add Action Profile Members (destinations)
#####
lag_ecmp = p4.TenantINCFrameworkIngress.lag_ecmp

mbr_base = 200000
port_1 = mbr_base + 1; lag_ecmp.entry_with_send(port_1, port=44).push()
port_2 = mbr_base + 2; lag_ecmp.entry_with_send(port_2, port=144).push()
# port_3 = mbr_base + 3; lag_ecmp.entry_with_send(port_3, port=3).push()

mbr_base = 100000
port_3 = mbr_base + 1; lag_ecmp.entry_with_send(port_3, port=145).push()

#####
# Create LAG or ECMP groups by adding entries to lag_ecmp_sel table
#####
lag_ecmp_sel = p4.TenantINCFrameworkIngress.lag_ecmp_sel

lag_1 = 2000;
lag_ecmp_sel.entry(SELECTOR_GROUP_ID=lag_1, MAX_GROUP_SIZE=8, ACTION_MEMBER_ID=[port_1, port_2], ACTION_MEMBER_STATUS=[True, True]).push()

lag_2 = 2001;
lag_ecmp_sel.entry(SELECTOR_GROUP_ID=lag_2, MAX_GROUP_SIZE=8, ACTION_MEMBER_ID=[port_3], ACTION_MEMBER_STATUS=[True]).push()


#####
# Create a nexthop 100 that will point to the LAG (group) created above
#####
nexthop = p4.TenantINCFrameworkIngress.nexthop
nexthop.entry(nexthop_id=100, SELECTOR_GROUP_ID=lag_1).push()
nexthop.entry(nexthop_id=101, SELECTOR_GROUP_ID=lag_2).push()

# Send all packets to nexthop 100
ipv4_lpm = p4.TenantINCFrameworkIngress.ipv4_lpm
# ipv4_lpm.entry_with_set_nexthop(dst_addr=IPAddress('10.100.0.102'), nexthop=101).push()
ipv4_lpm.set_default_with_set_nexthop(nexthop=100)

ipv4_host = p4.TenantINCFrameworkIngress.ipv4_host
ipv4_host.entry_with_set_nexthop(dst_addr=IPAddress('10.100.0.102'), nexthop=101).push()

arp_table = p4.TenantINCFrameworkIngress.arp_table
# arp_table.entry_with_set_nexthop(tpa=IPAddress('10.100.0.102'), op=0x0001, nexthop=101).push()
# arp_table.entry_with_set_nexthop(tpa=IPAddress('10.100.0.102'), op=0x0002, nexthop=101).push()
arp_table.entry_with_set_nexthop(tpa=IPAddress('10.100.0.102'), nexthop=101).push()
# arp_table.entry_with_set_nexthop(tpa=IPAddress('10.100.0.102'), nexthop=101).push()
arp_table.set_default_with_set_nexthop(nexthop=100)


# ipv6_lpm = p4.TenantINCFrameworkIngress.ipv6_lpm
# ipv6_lpm.set_default_with_set_nexthop(nexthop=100)

# Final programming
print("""
******************* PROGRAMMING RESULTS *****************
""")

print ("Table arp_table:")
arp_table.dump(table=True)
print ("Table ipv4_host:")
ipv4_lpm.dump(table=True)
print ("Table ipv4_host:")
ipv4_host.dump(table=True)
# print ("Table ipv6_host:")
# ipv6_lpm.dump(table=True)
print ("Table nexthop:")
nexthop.dump()  # There is a bug in SDE-9.2.0 that doesn't allow table=True here
print ("ActionSelector lag_ecmp_sel:")
lag_ecmp_sel.dump(table=True)
print ("ActionProfile lag_ecmp:")
lag_ecmp.dump(table=True)
