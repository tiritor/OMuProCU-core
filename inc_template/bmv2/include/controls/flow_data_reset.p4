/*************************************************************************
************************* C O N T R O L **********************************
*************************************************************************/

#ifndef __FLOW_DATA_RESET__
#define __FLOW_DATA_RESET__

control FlowDataResetter(inout headers_t hdr,
                       inout metadata_t meta,
                       inout standard_metadata_t standard_metadata) {

    

    action reset_flow_5tuple_action(){
        flow_src_ip_register.write(meta.flow_hash, (ipv4_address_t)0);
        flow_dst_ip_register.write(meta.flow_hash, (ipv4_address_t)0);
        flow_ip_protocol_register.write(meta.flow_hash, (ipv4_protocol_t)0);
        flow_src_port_register.write(meta.flow_hash, (l4_port_t)0);
        flow_dst_port_register.write(meta.flow_hash, (l4_port_t)0);
    }

#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))
    action reset_flow_record_data_registers_action() {
        // flow packet length
        flow_packet_length_min_register.write(meta.flow_hash, (packet_length_t) 0);
        flow_packet_length_max_register.write(meta.flow_hash, (packet_length_t) 0);
        flow_packet_length_mean_register.write(meta.flow_hash, (packet_length_t) 0);
        // flow inter arrival time
        flow_last_packet_timestamp_register.write(meta.flow_hash, (time_t) 0);
        flow_packet_inter_arrival_time_min_register.write(meta.flow_hash, (time_t) 0);
        flow_packet_inter_arrival_time_max_register.write(meta.flow_hash, (time_t) 0);
        flow_packet_inter_arrival_time_mean_register.write(meta.flow_hash, (time_t) 0);

        bidirectional_byte_register.write(meta.flow_hash, (byte_count_t) 0);
        bidirectional_packet_register.write(meta.flow_hash, (packet_count_t) 0);
        
        flow_first_packet_timestamp_register.write(meta.flow_hash, (time_t) 0);
        flow_last_packet_timestamp_register.write(meta.flow_hash, (time_t) 0);
        marked_malware_register.write(meta.flow_hash, 0);

    }
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))

#if (defined(FLOW_TYPE_BIFLOWS))
    action reset_flow_forward_record_data_registers_action() {

        flow_forward_last_packet_timestamp_register.write(meta.flow_hash, (time_t) 0);

        forward_byte_register.write(meta.flow_hash, (byte_count_t) 0);
        forward_packet_register.write(meta.flow_hash, (packet_count_t) 0);

        flow_forward_packet_length_min_register.write(meta.flow_hash, (packet_length_t) 0);
        flow_forward_packet_length_max_register.write(meta.flow_hash, (packet_length_t) 0);
        flow_forward_packet_length_mean_register.write(meta.flow_hash, (packet_length_t) 0);

        flow_forward_last_packet_timestamp_register.write(meta.flow_hash, (time_t) 0);
        flow_forward_packet_inter_arrival_time_min_register.write(meta.flow_hash, (time_t) 0);
        flow_forward_packet_inter_arrival_time_max_register.write(meta.flow_hash, (time_t) 0);
        flow_forward_packet_inter_arrival_time_mean_register.write(meta.flow_hash, (time_t) 0);

    }
    action reset_flow_backward_record_data_registers_action() {

        flow_backward_last_packet_timestamp_register.write(meta.flow_hash, (time_t) 0);

        backward_byte_register.write(meta.flow_hash, (byte_count_t) 0);
        backward_packet_register.write(meta.flow_hash, (packet_count_t) 0);

        flow_backward_packet_length_min_register.write(meta.flow_hash, (packet_length_t) 0);
        flow_backward_packet_length_max_register.write(meta.flow_hash, (packet_length_t) 0);
        flow_backward_packet_length_mean_register.write(meta.flow_hash, (packet_length_t) 0);

        flow_backward_last_packet_timestamp_register.write(meta.flow_hash, (time_t) 0);
        flow_backward_packet_inter_arrival_time_min_register.write(meta.flow_hash, (time_t) 0);
        flow_backward_packet_inter_arrival_time_max_register.write(meta.flow_hash, (time_t) 0);
        flow_backward_packet_inter_arrival_time_mean_register.write(meta.flow_hash, (time_t) 0);
    }
#endif  // (defined(FLOW_TYPE_BIFLOWS))

    action reset_flow_data_action(){
        reset_flow_5tuple_action();
#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))
        reset_flow_record_data_registers_action();
#endif
#if  (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
        reset_flow_forward_record_data_registers_action();
        reset_flow_backward_record_data_registers_action();
#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
    }

    apply {
        reset_flow_data_action();
    }

}
#endif // __FLOW_DATA_RESET__