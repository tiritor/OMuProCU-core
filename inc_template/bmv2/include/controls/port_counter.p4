/*************************************************************************
************************* C O N T R O L **********************************
*************************************************************************/

#ifndef __PORT_COUNTER__
#define __PORT_COUNTER__

#include "../define.p4"
#include "../header.p4"

/*************************************************************************
***************** I N G R E S S   P R O C E S S I N G ********************
*************************************************************************/

control PortCounterIngressControl(inout headers_t hdr,
                                  inout metadata_t meta,
                                  inout standard_metadata_t standard_metadata) {
    counter(NUM_SWITCH_PORTS_MAX - PORT_INDEX_OFFSET, CounterType.packets_and_bytes) ingress_port_counter;
    counter(1, CounterType.packets_and_bytes) drop_port_counter;

    apply {
        if (standard_metadata.instance_type == bmv2_v1model_instances_t.NORMAL &&
            standard_metadata.ingress_port != CPU_PORT &&
            standard_metadata.ingress_port != DROP_PORT &&
            standard_metadata.ingress_port < NUM_SWITCH_PORTS_MAX + PORT_INDEX_OFFSET) {
            ingress_port_counter.count((bit<32>) standard_metadata.ingress_port - PORT_INDEX_OFFSET);
        } else if (standard_metadata.instance_type == bmv2_v1model_instances_t.NORMAL && standard_metadata.ingress_port == DROP_PORT) {
            drop_port_counter.count(0);
        }
    }
}

/*************************************************************************
***************** E G R E S S   P R O C E S S I N G **********************
*************************************************************************/

control PortCounterEgressControl(inout headers_t hdr,
                                 inout metadata_t meta,
                                 inout standard_metadata_t standard_metadata) {
    counter(NUM_SWITCH_PORTS_MAX - PORT_INDEX_OFFSET, CounterType.packets_and_bytes) egress_port_counter;

    apply {
        if (standard_metadata.instance_type == bmv2_v1model_instances_t.NORMAL &&
            standard_metadata.egress_port != CPU_PORT &&
            standard_metadata.egress_port != DROP_PORT &&
            standard_metadata.egress_port < NUM_SWITCH_PORTS_MAX + PORT_INDEX_OFFSET) {
            egress_port_counter.count((bit<32>) standard_metadata.egress_port - PORT_INDEX_OFFSET);
        }
    }
}

#endif  // __PORT_COUNTER__
