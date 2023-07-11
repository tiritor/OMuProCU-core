/****************************************************************************
 * Copyright 2021-present Timo Geier
 *                        (timo.geier@cs.hs-fulda.de)
 *                        Fulda University of Applied Sciences
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 ****************************************************************************/

#include <core.p4>
#include <v1model.p4>

#include "include/define.p4"
#include "include/header.p4"
#include "include/parser.p4"
#include "include/checksum.p4"
#include "include/data.p4"
#include "include/controls/flow_data_update.p4"
#include "include/controls/flow_data_reset.p4"
#include "include/controls/port_counter.p4"

// OTFs Includes


#ifdef FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
#include "include/controls/flow_data_export.p4"
#endif

/*************************************************************************
***************** I N G R E S S   P R O C E S S I N G ********************
*************************************************************************/
control TenantRFClassificationIngress(inout headers_t hdr,
                              inout metadata_t meta,
                              inout standard_metadata_t standard_metadata) {
    PortCounterIngressControl() port_counter_ingress;
    FlowDataUpdater() flowDataUpdater;
    FlowDataResetter() flowDataResetter;


    bit bloom_filter_flow_monitoring_value;
    bit<8> classification_n_packets;
    

    action compute_flow_hash_action() {
#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
        ipv4_address_t ip_address_min;
        ipv4_address_t ip_address_max;
        l4_port_t l4_port_min;
        l4_port_t l4_port_max;
        ipv4_protocol_t ip_protocol;
        if (hdr.vxlan.isValid()) {
            if (hdr.inner_ipv4.src_addr > hdr.inner_ipv4.dst_addr) {
                ip_address_min = hdr.inner_ipv4.dst_addr;
                l4_port_min    = meta.ingress_meta.inner_l4_lookup.part2;
                ip_address_max = hdr.inner_ipv4.src_addr;
                l4_port_max    = meta.ingress_meta.inner_l4_lookup.part1;
            }
            else {
                ip_address_min = hdr.inner_ipv4.src_addr;
                l4_port_min    = meta.ingress_meta.inner_l4_lookup.part1;
                ip_address_max = hdr.inner_ipv4.dst_addr;
                l4_port_max    = meta.ingress_meta.inner_l4_lookup.part2;
            }
            ip_protocol = hdr.inner_ipv4.protocol;
        } else {
            if (hdr.ipv4.src_addr > hdr.ipv4.dst_addr) {
                ip_address_min = hdr.ipv4.dst_addr;
                l4_port_min    = meta.ingress_meta.l4_lookup.part2;
                ip_address_max = hdr.ipv4.src_addr;
                l4_port_max    = meta.ingress_meta.l4_lookup.part1;
            }
            else {
                ip_address_min = hdr.ipv4.src_addr;
                l4_port_min    = meta.ingress_meta.l4_lookup.part1;
                ip_address_max = hdr.ipv4.dst_addr;
                l4_port_max    = meta.ingress_meta.l4_lookup.part2;
            }
            ip_protocol = hdr.ipv4.protocol;
        }

#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
        ipv4_address_t ip_src_addr;
        ipv4_address_t ip_dst_addr;
        l4_port_t l4_src_port;
        l4_port_t l4_dst_port;
        ipv4_protocol_t ip_protocol;
        if(hdr.vxlan.isValid()) {
            ip_src_addr = hdr.inner_ipv4.src_addr;
            ip_dst_addr = hdr.inner_ipv4.dst_addr;
            l4_src_port = meta.ingress_meta.inner_l4_lookup.part1;
            l4_dst_port = meta.ingress_meta.inner_l4_lookup.part2;
            ip_protocol = hdr.inner_ipv4.protocol;
        } else {
            ip_src_addr = hdr.ipv4.src_addr;
            ip_dst_addr = hdr.ipv4.dst_addr;
            l4_src_port = meta.ingress_meta.l4_lookup.part1;
            l4_dst_port = meta.ingress_meta.l4_lookup.part2;
            ip_protocol = hdr.ipv4.protocol;
        }
#endif

        hash(meta.flow_hash,
             HashAlgorithm.crc32,                   // HashAlgorithm.crc16
             (bit<32>)0,                            // (bit<16>)0
#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
             {ip_src_addr,
              ip_dst_addr,
              l4_src_port,
              l4_dst_port,
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
             {ip_address_min,
              ip_address_max,
              l4_port_min,
              l4_port_max,
#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
              ip_protocol},
             (bit<32>)FLOW_MONITORING_SLOTS);            // (bit<16>)FLOW_MONITORING_SLOTS) 

    }

    action check_flow_hash_collision_action() {
        ipv4_protocol_t ip_protocol_tmp;
        ipv4_address_t src_ip_tmp;
        ipv4_address_t dst_ip_tmp;
        l4_port_t src_port_tmp;
        l4_port_t dst_port_tmp;

        flow_ip_protocol_register.read(ip_protocol_tmp, meta.flow_hash);
        flow_src_ip_register.read(src_ip_tmp, meta.flow_hash);
        flow_dst_ip_register.read(dst_ip_tmp, meta.flow_hash);
        flow_src_port_register.read(src_port_tmp, meta.flow_hash);
        flow_dst_port_register.read(dst_port_tmp, meta.flow_hash);

        if (hdr.ipv4.protocol != ip_protocol_tmp) {
            meta.ingress_meta.flow_hash_collision = 1;
            // hash_collision_counter.count(0);
            return;
        }
        if (hdr.vxlan.isValid()) {
            if (!((hdr.inner_ipv4.src_addr == src_ip_tmp && hdr.inner_ipv4.dst_addr == dst_ip_tmp) ||
                (hdr.inner_ipv4.src_addr == dst_ip_tmp && hdr.inner_ipv4.dst_addr == src_ip_tmp))) {
                meta.ingress_meta.flow_hash_collision = 1;
                // hash_collision_counter.count(0);
                return;
            }

            if (!((meta.ingress_meta.inner_l4_lookup.part1 == src_port_tmp && meta.ingress_meta.inner_l4_lookup.part2 == dst_port_tmp) ||
                (meta.ingress_meta.inner_l4_lookup.part1 == dst_port_tmp && meta.ingress_meta.inner_l4_lookup.part2 == src_port_tmp))) {
                meta.ingress_meta.flow_hash_collision = 1;
                // hash_collision_counter.count(0);
                return;
            }
        } else {
            if (!((hdr.ipv4.src_addr == src_ip_tmp && hdr.ipv4.dst_addr == dst_ip_tmp) ||
                (hdr.ipv4.src_addr == dst_ip_tmp && hdr.ipv4.dst_addr == src_ip_tmp))) {
                meta.ingress_meta.flow_hash_collision = 1;
                // hash_collision_counter.count(0);
                return;
            }

            if (!((meta.ingress_meta.l4_lookup.part1 == src_port_tmp && meta.ingress_meta.l4_lookup.part2 == dst_port_tmp) ||
                (meta.ingress_meta.l4_lookup.part1 == dst_port_tmp && meta.ingress_meta.l4_lookup.part2 == src_port_tmp))) {
                meta.ingress_meta.flow_hash_collision = 1;
                // hash_collision_counter.count(0);
                return;
            }
        }
    }

    action remove_original_packet_headers_action() {
        // hdr.flow_export_request.setInvalid();
        hdr.ipv4.setInvalid();
        hdr.ipv4_options.setInvalid();
        hdr.icmp.setInvalid();
        hdr.tcp.setInvalid();
        hdr.tcp_options.setInvalid();
        hdr.udp.setInvalid();

#ifdef FLOW_TYPE_FLOWS
        truncate((bit<32>)(14 + 5 + FLOW_RECORD_DATA_H_LENGTH));                                    // ethernet, flow_export_response, flow_record_data

#elif defined(FLOW_TYPE_BIFLOWS)
        truncate((bit<32>)(14 + 5 + BIFLOW_RECORD_DATA_H_LENGTH));                                  // ethernet, flow_export_response, biflow_record_data

#endif
    }

    action swap_flow_export_packet_macs_action() {
        mac_address_t mac_addr_tmp = hdr.ethernet.src_addr;
        hdr.ethernet.src_addr = hdr.ethernet.dst_addr;
        hdr.ethernet.dst_addr = mac_addr_tmp;
    }

    action drop_action() {
        mark_to_drop(standard_metadata);
    }

    action send_to_port_action(port_id_t egress_port) {
        standard_metadata.egress_spec = egress_port;
    }

    action l3_switch_action(port_id_t egress_port, mac_address_t source_mac, mac_address_t destination_mac) {
        hdr.ethernet.dst_addr = source_mac;
        hdr.ethernet.src_addr = destination_mac;

        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;

        send_to_port_action(egress_port);
    }

    action register_flow_5tuple_action() {
        ipv4_address_t ip_src_addr;
        ipv4_address_t ip_dst_addr;
        l4_port_t l4_src_port;
        l4_port_t l4_dst_port;
        ipv4_protocol_t ip_protocol;

        if(hdr.vxlan.isValid()) {
            ip_src_addr = hdr.inner_ipv4.src_addr;
            ip_dst_addr = hdr.inner_ipv4.dst_addr;
            ip_protocol = hdr.inner_ipv4.protocol;
            l4_src_port = meta.ingress_meta.inner_l4_lookup.part1;
            l4_dst_port = meta.ingress_meta.inner_l4_lookup.part2;
        } else {
            ip_src_addr = hdr.ipv4.src_addr;
            ip_dst_addr = hdr.ipv4.dst_addr;
            ip_protocol = hdr.ipv4.protocol;
            l4_src_port = meta.ingress_meta.l4_lookup.part1;
            l4_dst_port = meta.ingress_meta.l4_lookup.part2;
        }

        flow_src_ip_register.write(meta.flow_hash, ip_src_addr);
        flow_dst_ip_register.write(meta.flow_hash, ip_dst_addr);
        flow_ip_protocol_register.write(meta.flow_hash, ip_protocol);
        flow_src_port_register.write(meta.flow_hash, l4_src_port);
        flow_dst_port_register.write(meta.flow_hash, l4_dst_port);
    }

#ifdef STATIC_ROUTING
    action static_forwarding_action() {
        if (standard_metadata.ingress_port == 1) {
            standard_metadata.egress_spec = 2;
        }
        else if (standard_metadata.ingress_port == 3) {
            standard_metadata.egress_spec = 4;
        }
        else if (standard_metadata.ingress_port == 2) {
            standard_metadata.egress_spec = 1;
        }
        else {  // standard_metadata.ingress_port == 4
            standard_metadata.egress_spec = 3;
        }
    }
#endif
#if defined(DYNAMIC_ROUTING) && DYNAMIC_ROUTING
    table ipv4_host_table {
        key = {
            hdr.ipv4.dst_addr: exact;
        }
        actions = {
            send_to_port_action;
            @defaultonly NoAction;
        }
        const default_action = NoAction();
        size = TABLE_SIZE_IPV4_HOST;
    }

    table ipv4_lpm_table {
        key = {
            hdr.ipv4.dst_addr: lpm;
        }
        actions = {
            send_to_port_action;
            @defaultonly drop_action;
        }
        const default_action = drop_action();
        size = TABLE_SIZE_IPV4_LPM;
    }

    table nexthop_table {
        key = {
            standard_metadata.egress_spec: exact;
        }
        actions = {
            send_to_port_action;
            l3_switch_action;
            drop_action;
            @defaultonly NoAction;
        }
        const default_action = NoAction();
        size = TABLE_SIZE_NEXTHOP;
    }
#endif

    apply {
        if (hdr.ethernet.ether_type == ether_types_t.FLOW_MONITORING && standard_metadata.ingress_port == CPU_PORT) {
            if (hdr.flow_mon.message_reason == flow_monitoring_reasons_t.IDLE_TIMEOUT) {
                // FIXME: Packets are mirrored with original payload (Should only be sending the modified packet)
                meta.flow_hash = hdr.flow_mon.flow_hash;
                // log_msg("Got reset message for hash {}", {meta.flow_hash});
                flowDataResetter.apply(hdr, meta, standard_metadata);
                bloom_filter_flow_monitoring.write(meta.flow_hash, 0);
                // hdr.flow_mon.setInvalid();
                hdr.flow_mon.message_reason = flow_monitoring_reasons_t.IDLE_TIMEOUT_ACK;
                hdr.flow_mon.flow_hash = meta.flow_hash;
                // hdr.flow_mon.setValid();
                bit<1> bloom_filter_test;
                bloom_filter_flow_monitoring.read(bloom_filter_test, meta.flow_hash);
                packet_count_t bipackets;
                bidirectional_packet_register.read(bipackets, meta.flow_hash);
                log_msg("Flow Hash: {}, Reason: {}, Bloom Filter: {}, Bi-Packets: {}", {hdr.flow_mon.flow_hash, hdr.flow_mon.message_reason, bloom_filter_test, bipackets});

                swap_flow_export_packet_macs_action();
                send_to_port_action(CPU_PORT);
                // clone(CloneType.I2E, 99);
            }
            else {
                drop_action();
            }
            exit;   // return;
        } 
        // else if (standard_metadata.instance_type == bmv2_v1model_instances_t.RECIRCULATION) {
        //     send_to_port_action(CPU_PORT);
        // }

        port_counter_ingress.apply(hdr, meta, standard_metadata);
#if defined(STATIC_ROUTING) && STATIC_ROUTING
        // send_to_port_action(3);
        static_forwarding_action();
#endif

        if (standard_metadata.instance_type == bmv2_v1model_instances_t.NORMAL && hdr.ethernet.ether_type == ether_types_t.IPV4) {
#if defined(DYNAMIC_ROUTING) && DYNAMIC_ROUTING
            if (hdr.ipv4.isValid() && hdr.ipv4.ttl > 1) {
                if (!ipv4_host_table.apply().hit) {
                    if(!ipv4_lpm_table.apply().hit) {
                        nexthop_table.apply();
                    }
                }
            } else {
                drop_action();
                exit;   // return;
            }
#endif
            compute_flow_hash_action();

            bloom_filter_flow_monitoring.read(bloom_filter_flow_monitoring_value, meta.flow_hash);
            if (bloom_filter_flow_monitoring_value == 0) {
                bloom_filter_flow_monitoring.write(meta.flow_hash, 1);

                register_flow_5tuple_action();
                flow_counter.count(0);
            } else {

#if FLOW_INACTIVE_TIMEOUT_MECHANISM_CLEAR_REGISTERS
                time_t flow_last_packet_timestamp; 
                flow_last_packet_timestamp_register.read(flow_last_packet_timestamp, meta.flow_hash);
                if((hdr.pm.timestamp - flow_last_packet_timestamp) > (FLOW_INACTIVE_TIMEOUT * 1000000)) {
                    // Flow hitted inactive timeout!
                    flowDataResetter.apply(hdr, meta, standard_metadata);
                    register_flow_5tuple_action();
                    flow_counter.count(0);
                } else {
#endif // FLOW_INACTIVE_TIMEOUT_MECHANISM_CLEAR_REGISTERS
                    // Hash collision check
                    meta.ingress_meta.flow_hash_collision = 0;
                    check_flow_hash_collision_action();
                    if (meta.ingress_meta.flow_hash_collision == 1){
                        hash_collision_counter.count(0);
                        exit;
                    }
#if FLOW_INACTIVE_TIMEOUT_MECHANISM_CLEAR_REGISTERS
                }
#endif // FLOW_INACTIVE_TIMEOUT_MECHANISM_CLEAR_REGISTERS
            }

            // [General Flow Monitoring]
            flowDataUpdater.apply(hdr, meta, standard_metadata);

            // [In-Network Tenant Controller --> OTFs]
            if (hdr.vxlan.isValid()) { 
			  
			 }


            // [Conditional Data Export (CDE)]
            if ((bool) meta.tenant_meta.export_flag) { // 
                clone_preserving_field_list(CloneType.I2E, MIRROR_SESSION_ID, CLONE_FL_1);
            }

        }
    }
}

/*************************************************************************
***************** E G R E S S   P R O C E S S I N G **********************
*************************************************************************/
control TenantRFClassificationEgress(inout headers_t hdr,
                             inout metadata_t meta,
                             inout standard_metadata_t standard_metadata) {
    PortCounterEgressControl() port_counter_egress;

#ifdef TRACK_PROCESSING_TIME
    counter(MAX_PROCESSING_TIME, CounterType.packets) processing_time_counter;
    counter(MAX_PROCESSING_TIME, CounterType.packets) tenant_42_processing_time_counter;
    counter(MAX_PROCESSING_TIME, CounterType.packets) tenant_123_processing_time_counter;
#endif // TRACK_PROCESSING_TIME

#ifdef FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
    FlowDataExport() flowDataExporter;

    action remove_export_packet_headers_action() {
        hdr.ethernet.ether_type = ether_types_t.IPV4;

        hdr.flow_export_response.setInvalid();
#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))        
        hdr.flow_record_data.setInvalid();
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_SUBFLOWS))
#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))    
        hdr.biflow_record_data.setInvalid();
#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))        
    }

    action remove_original_packet_headers_action() {
        hdr.flow_export_request.setInvalid();
        hdr.flow_mon.setInvalid();
        hdr.ipv4.setInvalid();
        hdr.ipv4_options.setInvalid();
        hdr.icmp.setInvalid();
        hdr.tcp.setInvalid();
        hdr.tcp_options.setInvalid();
        hdr.udp.setInvalid();
        hdr.inner_ethernet.setInvalid();
        hdr.inner_ipv4.setInvalid();
        hdr.inner_tcp.setInvalid();
        hdr.inner_tcp_options.setInvalid();
        hdr.inner_udp.setInvalid();
        hdr.vxlan.setInvalid();
        hdr.pm.setInvalid();

#ifdef FLOW_TYPE_FLOWS
        // truncate((bit<32>)(14 + 5 + FLOW_RECORD_DATA_H_LENGTH));                                    // ethernet, flow_export_response, flow_record_data
        truncate((bit<32>)(14 + FLOW_EXPORT_RESPONSE_H_LENGTH + TENANT_H_DATA_LENGTH + ANALYZER_DATA_H_LENGTH + FLOW_RECORD_DATA_H_LENGTH));                                    // ethernet, analyzer, flow_record_data

        // truncate((bit<32>)(14 + FLOW_RECORD_DATA_H_LENGTH));                                    // ethernet, flow_record_data

#elif defined(FLOW_TYPE_BIFLOWS)
        truncate((bit<32>)(14 + FLOW_EXPORT_RESPONSE_H_LENGTH + TENANT_H_DATA_LENGTH + ANALYZER_DATA_H_LENGTH + BIFLOW_RECORD_DATA_H_LENGTH));                                  // ethernet, flow_export_response, biflow_record_data

#endif
    }

    action swap_flow_export_packet_macs_action() {
        mac_address_t mac_addr_tmp = hdr.ethernet.src_addr;
        hdr.ethernet.src_addr = hdr.ethernet.dst_addr;
        hdr.ethernet.dst_addr = mac_addr_tmp;
    }
#endif  // FLOW_EXPORT_STRATEGY_EXPORT_PACKETS

    apply {

#ifdef FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
        if (standard_metadata.instance_type == bmv2_v1model_instances_t.INGRESS_CLONE) {
            meta.flow_type = flow_type;
            meta.flow_export_reason = flow_export_reasons_t.EXPORT_TRIGGERED;
            remove_original_packet_headers_action();
            flowDataExporter.apply(hdr, meta, standard_metadata);
            log_msg("EXPORT;");
        }
#endif  // FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
        else if (standard_metadata.instance_type == bmv2_v1model_instances_t.NORMAL) {
            port_counter_egress.apply(hdr, meta, standard_metadata);
            
#ifdef TRACK_PROCESSING_TIME
            if (meta.feature_meta.bidirectional_packets == classification_n_packets) {
                if(hdr.vxlan.isValid()){
                    bit<48> processing_time = (standard_metadata.egress_global_timestamp - standard_metadata.ingress_global_timestamp - ((bit<48>) standard_metadata.deq_timedelta));
                    // log_msg("Processing TIme: {}", {processing_time});
                    if (processing_time < MAX_PROCESSING_TIME){
                        processing_time_counter.count((bit<32>) processing_time);
                    } else {
                        log_msg("PROCESSING_TIME;TIME: {}", {processing_time});
                    }
                } else {
                    if (hdr.vxlan.vni  == 42){ 
                        bit<48> processing_time = (standard_metadata.egress_global_timestamp - standard_metadata.ingress_global_timestamp - ((bit<48>) standard_metadata.deq_timedelta));
                    // log_msg("Processing TIme: {}", {processing_time});
                    if (processing_time < MAX_PROCESSING_TIME){
                        tenat_42_processing_time_counter.count((bit<32>) processing_time);
                    } else {
                        log_msg("PROCESSING_TIME;TENANT_42_TIME: {}", {processing_time});
                    }
                    } else if (hdr.vxlan.vni == 123) {
                        bit<48> processing_time = (standard_metadata.egress_global_timestamp - standard_metadata.ingress_global_timestamp - ((bit<48>) standard_metadata.deq_timedelta));
                    // log_msg("Processing TIme: {}", {processing_time});
                    if (processing_time < MAX_PROCESSING_TIME){
                        tenant_123_processing_time_counter.count((bit<32>) processing_time);
                    } else {
                        log_msg("PROCESSING_TIME;TENANT_123_TIME: {}", {processing_time});
                    }
                    }
                }
            }
#endif // TRACK_PROCESSING_TIME
        }
    }
}

/*************************************************************************
************************* S W I T C H ************************************
*************************************************************************/
V1Switch(TenantRFClassificationParser(),
         TenantRFClassificationVerifyChecksum(),
         TenantRFClassificationIngress(),
         TenantRFClassificationEgress(),
         TenantRFClassificationComputeChecksum(),
         TenantRFClassificationDeparser()) main;