# Final programming
print("""
******************* PROGRAMMING RESULTS *****************
""")
p4 = bfrt.tenant_inc.pipe
nexthop = p4.TenantINCFrameworkIngress.nexthop

lag_ecmp_sel = p4.TenantINCFrameworkIngress.lag_ecmp_sel
lag_ecmp = p4.TenantINCFrameworkIngress.lag_ecmp
ipv4_lpm = p4.TenantINCFrameworkIngress.ipv4_lpm
ipv4_host = p4.TenantINCFrameworkIngress.ipv4_host
arp_table = p4.TenantINCFrameworkIngress.arp_table


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
