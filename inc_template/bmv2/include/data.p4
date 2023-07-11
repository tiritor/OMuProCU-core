#ifndef __DATA__
#define __DATA__

// flow existence
    register<bit<1>>(FLOW_MONITORING_SLOTS) bloom_filter_flow_monitoring;


    // register<bit<1>>(FLOW_MONITORING_SLOTS) bloom_filter_allowed;
    
    // Blacklisted flows
    register<bit<1>>(FLOW_MONITORING_SLOTS) marked_malware_register;

    // flow timeouts
    // register<time_t>(FLOW_MONITORING_SLOTS) flow_active_timeout_register;
    // register<time_t>(FLOW_MONITORING_SLOTS) flow_inactive_timeout_register;

    // flow 5-tuple
    register<ipv4_address_t>(FLOW_MONITORING_SLOTS) flow_src_ip_register;
    register<ipv4_address_t>(FLOW_MONITORING_SLOTS) flow_dst_ip_register;
    register<ipv4_protocol_t>(FLOW_MONITORING_SLOTS) flow_ip_protocol_register;
    register<l4_port_t>(FLOW_MONITORING_SLOTS) flow_src_port_register;
    register<l4_port_t>(FLOW_MONITORING_SLOTS) flow_dst_port_register;


    // Additional Features
    // register<bit<16>>(FLOW_MONITORING_SLOTS) fwd_ack_flag_register;

    // SwitchTreeP
    register<bit<1>>(1) switchtreep_register;

    // Probability Threshold Registers
    register<bit<8>>(1) probability_uncertain_register;
    register<bit<8>>(1) probability_certain_register;
    register<bit<8>>(1) classification_after_n_packets_register;

    // Skip Classification Register
    register<bit<1>>(1) skip_classification_register;

    register<bit<32>>(1) malware_register;

    register<time_t>(1) last_timestamp_register;

    // Debug counter
    counter(1, CounterType.packets) hash_collision_counter;
    // counter(1, CounterType.packets) hash_2_collision_counter;
    counter(1, CounterType.packets) flow_counter;
    // counter(1, CounterType.packets) not_classified_counter;
    counter(1, CounterType.packets) classification_counter;
    counter(1024, CounterType.packets) tenant_classification_counter;
    // counter(1, CounterType.packets) analyzed_counter;

    // RF Tracking Features
    // counter(1, CounterType.packets_and_bytes) marked_benign_counter;
    // counter(1, CounterType.packets_and_bytes) marked_malware_counter;
    // counter(1, CounterType.packets_and_bytes) marked_malware_first_seen_counter;
    // counter(1, CounterType.packets) marked_malware_skipped_classification_counter;
    // counter(FLOW_MONITORING_SLOTS, CounterType.packets_and_bytes) marked_benign_flow_counter;
    // counter(FLOW_MONITORING_SLOTS, CounterType.packets_and_bytes) marked_malware_flow_counter;
    // counter(FLOW_MONITORING_SLOTS, CounterType.packets_and_bytes) marked_malware_flow_first_seen_counter;

    // RF Validation Counter
//     counter(1, CounterType.packets_and_bytes) true_positive_counter;
//     counter(1, CounterType.packets_and_bytes) false_positive_counter;
//     counter(1, CounterType.packets_and_bytes) true_negative_counter;
//     counter(1, CounterType.packets_and_bytes) false_negative_counter;
//     counter(101, CounterType.packets_and_bytes) true_positive_prob_counter;
//     counter(101, CounterType.packets_and_bytes) false_positive_prob_counter;
//     counter(101, CounterType.packets_and_bytes) true_negative_prob_counter;
//     counter(101, CounterType.packets_and_bytes) false_negative_prob_counter;
// #if RF_TREE_COUNT == 1
//     counter(NODE_COUNT, CounterType.packets_and_bytes) node_hit_counter;
//     counter(NODE_COUNT, CounterType.packets_and_bytes) false_negative_node_hit_counter;
//     counter(NODE_COUNT, CounterType.packets_and_bytes) false_positive_node_hit_counter;
//     counter(NODE_COUNT, CounterType.packets_and_bytes) true_positive_node_hit_counter;
//     counter(NODE_COUNT, CounterType.packets_and_bytes) true_negative_node_hit_counter;
// #endif

    // counter(1, CounterType.packets_and_bytes) marked_true_positive_counter;
    // counter(1, CounterType.packets_and_bytes) marked_false_negative_counter;
    // counter(1, CounterType.packets_and_bytes) marked_false_positive_counter;
    // counter(1, CounterType.packets_and_bytes) marked_true_negative_counter;

    // RF Certainty Counter
    // counter(1, CounterType.packets_and_bytes) attack_uncertain_counter;
    // counter(1, CounterType.packets_and_bytes) attack_certain_counter;
    // counter(1, CounterType.packets_and_bytes) benign_uncertain_counter;
    // counter(1, CounterType.packets_and_bytes) benign_certain_counter;

    // flow packets and bytes counter
    counter(FLOW_MONITORING_SLOTS, CounterType.packets_and_bytes) flow_packets_bytes_counter;


#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
    // biflow forward packets and bytes counter
    counter(FLOW_MONITORING_SLOTS, CounterType.packets_and_bytes) flow_forward_packets_bytes_counter;
    // biflow backward packets and bytes counter
    counter(FLOW_MONITORING_SLOTS, CounterType.packets_and_bytes) flow_backward_packets_bytes_counter;

#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))
    // flow packet length
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_packet_length_min_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_packet_length_max_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_packet_length_mean_register;

#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))


#if (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))
    // flow packet inter-arrival time
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_first_packet_timestamp_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_last_packet_timestamp_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_packet_inter_arrival_time_min_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_packet_inter_arrival_time_max_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_packet_inter_arrival_time_mean_register;
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))
#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
    // biflow forward packet inter-arrival time
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_first_packet_timestamp_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_last_packet_timestamp_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_packet_inter_arrival_time_min_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_packet_inter_arrival_time_max_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_packet_inter_arrival_time_mean_register;
    // biflow backward packet inter-arrival time
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_first_packet_timestamp_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_last_packet_timestamp_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_packet_inter_arrival_time_min_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_packet_inter_arrival_time_max_register;
    register<bit<FLOW_MONITORING_TIMESTAMP_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_packet_inter_arrival_time_mean_register;
#endif  // (defined(FLOW_TYPE_FLOWS) || defined(FLOW_TYPE_BIFLOWS))

    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) bidirectional_byte_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) bidirectional_packet_register;

#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) forward_byte_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) forward_packet_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) backward_byte_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) backward_packet_register;
    // biflow forward packet length
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_packet_length_min_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_packet_length_max_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_forward_packet_length_mean_register;
    // biflow backward packet length
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_packet_length_min_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_packet_length_max_register;
    register<bit<FLOW_MONITORING_VALUE_WIDTH>>(FLOW_MONITORING_SLOTS) flow_backward_packet_length_mean_register;

#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))


#endif // __DATA__