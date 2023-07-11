/*************************************************************************
***************** D E F I N E S / C O N S T A N T S **********************
*************************************************************************/

#ifndef __DEFINE__
#define __DEFINE__

#define TABLE_SIZE_IPV4_HOST 4096
#define TABLE_SIZE_IPV4_LPM 4096

#define TABLE_SIZE_NEXTHOP 32

#define TENANTS_COUNT 16777215

#define PROB_FLOAT 1
#define MAX_PROB_VALUE 101 * PROB_FLOAT

#define CLASS_NOT_SET 10000 // A big number

#ifndef TENANT_CLASSIFICATION
#define TENANT_CLASSIFICATION 0
#endif

// #ifndef TRACK_PROCESSING_TIME
// #define TRACK_PROCESSING_TIME
// #define MAX_PROCESSING_TIME 9*100000
// #endif

#ifndef STATIC_ROUTING // && !defined(DYNAMIC_ROUTING)
#define STATIC_ROUTING 0
#endif

#if !defined(DYNAMIC_ROUTING) && !STATIC_ROUTING
#define DYNAMIC_ROUTING 1
#endif

#ifndef AFTER_CLASSIFIED_HANDLING
#define AFTER_CLASSIFIED_HANDLING 0
#endif

#ifndef FLOW_INACTIVE_TIMEOUT_MECHANISM
#define FLOW_INACTIVE_TIMEOUT_MECHANISM 1
#endif

#ifndef FLOW_INACTIVE_TIMEOUT_MECHANISM_CLEAR_REGISTERS
#define FLOW_INACTIVE_TIMEOUT_MECHANISM_CLEAR_REGISTERS 1
#endif

#ifndef USE_PM
#define USE_PM 1
#endif

#ifndef RF_TREE_COUNT 
#define RF_TREE_COUNT 1
#endif

#ifndef FLOW_INACTIVE_TIMEOUT 
#define FLOW_INACTIVE_TIMEOUT 16
#endif

#ifndef FLOW_ACTIVE_TIMEOUT 
#define FLOW_ACTIVE_TIMEOUT 16
#endif

const bit<8> IP_PROTOCOLS_ICMP = 1;
const bit<8> IP_PROTOCOLS_TCP  = 6;
const bit<8> IP_PROTOCOLS_UDP  = 17;
enum bit<8> ip_protos_t {
    ICMP = IP_PROTOCOLS_ICMP,
    TCP  = IP_PROTOCOLS_TCP,
    UDP  = IP_PROTOCOLS_UDP
}

enum bit<8> flow_monitoring_reasons_t {
    IDLE_TIMEOUT = 0,
    IDLE_TIMEOUT_ACK = 1
}

error {
    IPv4IncorrectVersion,
    IPv4ChecksumError,
    IPv4HeaderTooShort,
    IPv4OptionsNotSupported
}

// VXLAN Definitions
#define UDP_PORT_VXLAN 4789

const bit<9> CPU_PORT          = 510;
const bit<9> DROP_PORT         = 511;
const bit<9> HOST_NETWORK_PORT = 1;

// #ifndef FLOW_ACTIVE_TIMEOUT
//     #define FLOW_ACTIVE_TIMEOUT 120
// #endif   // FLOW_ACTIVE_TIMEOUT
// #ifndef FLOW_INACTIVE_TIMEOUT
//     #define FLOW_INACTIVE_TIMEOUT 30
// #endif   // FLOW_INACTIVE_TIMEOUT
// const time_t FLOW_MONITORING_ACTIVE_TIMEOUT   = FLOW_ACTIVE_TIMEOUT * 1000000;     // 120 seconds
// const time_t FLOW_MONITORING_INACTIVE_TIMEOUT = FLOW_INACTIVE_TIMEOUT * 10000000;  // 030 seconds
// enum bit<48> flow_timeouts_t {
//     ACTIVE   = FLOW_MONITORING_ACTIVE_TIMEOUT,
//     INACTIVE = FLOW_MONITORING_INACTIVE_TIMEOUT
// }

const int FLOW_MONITORING_SLOTS =    1048576; // Used Value at the moment: 2^20: 1048576; Last possible value: 2^22: 4194304; Tradeoff-Value in old version: 2^21: 2097152; For CICIDS2017 Wed --> 2^19: 524288, 2^20: 1048576

enum bit<8> flow_types_t {
    FLOWS      = 0,
    BIFLOWS    = 1,
    SUBFLOWS   = 2,
    BISUBFLOWS = 3
}

#ifdef FLOW_TYPE_FLOWS
    const bit<8> flow_type = flow_types_t.FLOWS;
#elif defined(FLOW_TYPE_BIFLOWS)
    const bit<8> flow_type = flow_types_t.BIFLOWS;
#endif

#ifdef FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
    const bit<32> MIRROR_SESSION_ID  = 99;
#endif  // FLOW_EXPORT_STRATEGY_EXPORT_PACKETS

#ifdef FLOW_EXPORT_STRATEGY_EXPORT_PACKETS
    enum bit<8> flow_export_reasons_t {
        ACTIVE_TIMEOUT_HIT      = 0,
        INACTIVE_TIMEOUT_HIT    = 1,
        TCP_CONNECTION_FINISHED = 2,
        EXPORT_TRIGGERED        = 3,
        UNCERTAIN_CLASSIFIED    = 4
    }
#endif  // FLOW_EXPORT_STRATEGY_EXPORT_PACKETS

#if (!defined(FLOW_TYPE_FLOWS) && !defined(FLOW_TYPE_SUBFLOWS) && !defined(FLOW_TYPE_BIFLOWS) && !defined(FLOW_TYPE_BISUBFLOWS))
    #define FLOW_TYPE_FLOWS
#endif  // (!defined(FLOW_TYPE_FLOWS) && !defined(FLOW_TYPE_SUBFLOWS) && !defined(FLOW_TYPE_BIFLOWS) && !defined(FLOW_TYPE_BISUBFLOWS))

#if (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))
    enum bit<8> flow_direction_t {
        FORWARD  = 0,
        BACKWARD = 1
    }
#endif  // (defined(FLOW_TYPE_BIFLOWS) || defined(FLOW_TYPE_BISUBFLOWS))

const bit<8> TCP_FIN_FLAG = 0x01;
const bit<8> TCP_SYN_FLAG = 0x02;
const bit<8> TCP_RST_FLAG = 0x04;
const bit<8> TCP_PSH_FLAG = 0x08;
const bit<8> TCP_ACK_FLAG = 0x10;
const bit<8> TCP_URG_FLAG = 0x20;
const bit<8> TCP_ECE_FLAG = 0x40;
const bit<8> TCP_CWR_FLAG = 0x80;
enum bit<8> tcp_flags_t {
    FIN  = TCP_FIN_FLAG,
    SYN  = TCP_SYN_FLAG,
    RST  = TCP_RST_FLAG,
    PSH  = TCP_PSH_FLAG,
    ACK  = TCP_ACK_FLAG,
    URG  = TCP_URG_FLAG,
    ECE  = TCP_ECE_FLAG,
    CWR  = TCP_CWR_FLAG
}

#define NUM_SWITCH_PORTS_MAX 21
#define PORT_INDEX_OFFSET 1


const bit<32> BMV2_V1MODEL_INSTANCE_TYPE_NORMAL        = 0;
const bit<32> BMV2_V1MODEL_INSTANCE_TYPE_INGRESS_CLONE = 1;
const bit<32> BMV2_V1MODEL_INSTANCE_TYPE_EGRESS_CLONE  = 2;
const bit<32> BMV2_V1MODEL_INSTANCE_TYPE_COALESCED     = 3;
const bit<32> BMV2_V1MODEL_INSTANCE_TYPE_RECIRCULATION = 4;
const bit<32> BMV2_V1MODEL_INSTANCE_TYPE_REPLICATION   = 5;
const bit<32> BMV2_V1MODEL_INSTANCE_TYPE_RESUBMIT      = 6;
enum bit<32> bmv2_v1model_instances_t {
    NORMAL        = BMV2_V1MODEL_INSTANCE_TYPE_NORMAL,
    INGRESS_CLONE = BMV2_V1MODEL_INSTANCE_TYPE_INGRESS_CLONE,
    EGRESS_CLONE  = BMV2_V1MODEL_INSTANCE_TYPE_EGRESS_CLONE,
    COALESCED     = BMV2_V1MODEL_INSTANCE_TYPE_COALESCED,
    RECIRCULATION = BMV2_V1MODEL_INSTANCE_TYPE_RECIRCULATION,
    REPLICATION   = BMV2_V1MODEL_INSTANCE_TYPE_REPLICATION,
    RESUBMIT      = BMV2_V1MODEL_INSTANCE_TYPE_RESUBMIT
}

const bit<8> EMPTY_FL    = 0;
const bit<8> RESUB_FL_1  = 1;
const bit<8> CLONE_FL_1  = 2; // Conditional Data Export
const bit<8> RECIRC_FL_1 = 3;
enum bit<8> bmv2_v1model_fl_t {
    EMPTY_FL = EMPTY_FL,
    RESUB_FL_1 = RESUB_FL_1,
    CLONE_FL_1 = CLONE_FL_1,
    RECIRC_FL_1 = RECIRC_FL_1
}


// https://github.com/p4lang/p4c/issues/1232#issuecomment-623030697
// This must be set per Window Size matching exponent
// SWS 4 --> 2**_2_ = 4
// SWS 8 --> 2**_3_ = 8

// #define MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH 7  // 2**7=128 => HISTORY_WEIGHT = 127 && CURRENT_WEIGHT = 1
#define MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH SUBFLOW_WINDOW_POWER_OF_TWO  // defined with preprocessor declaration

#define FLOW_MONITORING_VALUE_WIDTH_EXTENDED (FLOW_MONITORING_VALUE_WIDTH + MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH + 1)
#define FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED (FLOW_MONITORING_TIMESTAMP_WIDTH + MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH + 1)

#endif  // __DEFINE__
