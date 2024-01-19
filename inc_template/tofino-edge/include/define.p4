/*************************************************************************
***************** D E F I N E S / C O N S T A N T S **********************
*************************************************************************/

#ifndef __DEFINE__
#define __DEFINE__

#define TENANTS_COUNT 16777215

#ifndef MAX_PROFILE_MEMBERS
#define MAX_PROFILE_MEMBERS 2048
#endif

#ifndef MAX_GROUPS
#define MAX_GROUPS 1024 
#endif

/* The number of required hash bits depends on both the selection algorithm 
 * (resilient or fair) and the maximum group size
 *
 * The rules are as follows:
 *
 * if MAX_GROUP_SIZE <= 120:      subgroup_select_bits = 0
 * elif MAX_GROUP_SIZE <= 3840:   subgroup_select_bits = 10
 * elif MAX_GROUP_SIZE <= 119040: subgroup_select_bits = 15
 * else: ERROR
 *
 * The rules for the hash size are:
 *
 * FAIR:      14 + subgroup_select_bits
 * RESILIENT: 51 + subgroup_select_bits
 *
 */
const int            MAX_GROUP_SIZE = 240;
const SelectorMode_t SELECTION_MODE = SelectorMode_t.FAIR;
const int            HASH_WIDTH     = 24;


/* 
 * Since we will be calculating hash in 32-bit pieces, we will have this 
 * definition, which will be either bit<32>, bit<64> or bit<96> depending
 * on HASH_WIDTH
 */
typedef bit<(((HASH_WIDTH + 32)/32)*32)> selector_hash_t;

const bit<8> IP_PROTOCOLS_ICMP = 1;
const bit<8> IP_PROTOCOLS_IGMP = 2;
const bit<8> IP_PROTOCOLS_TCP  = 6;
const bit<8> IP_PROTOCOLS_UDP  = 17;
enum bit<8> ip_protos_t {
    ICMP = IP_PROTOCOLS_ICMP,
    IGMP = IP_PROTOCOLS_IGMP,
    TCP  = IP_PROTOCOLS_TCP,
    UDP  = IP_PROTOCOLS_UDP
}

enum bit<8> flow_monitoring_reasons_t {
    IDLE_TIMEOUT = 0,
    IDLE_TIMEOUT_ACK = 1
}

typedef bit<16>   nexthop_id_t;


/******** TABLE SIZING **********/
const bit<32> LAG_ECMP_SIZE = 16384;

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


const int FLOW_MONITORING_SLOTS =    1024; // Used Value at the moment: 2^10: 1024;

enum bit<8> flow_types_t {
    FLOWS      = 0,
    BIFLOWS    = 1,
    SUBFLOWS   = 2,
    BISUBFLOWS = 3
}

#if (!defined(FLOW_TYPE_FLOWS) && !defined(FLOW_TYPE_SUBFLOWS) && !defined(FLOW_TYPE_BIFLOWS) && !defined(FLOW_TYPE_BISUBFLOWS))
    #define FLOW_TYPE_FLOWS
#endif  // (!defined(FLOW_TYPE_FLOWS) && !defined(FLOW_TYPE_SUBFLOWS) && !defined(FLOW_TYPE_BIFLOWS) && !defined(FLOW_TYPE_BISUBFLOWS))

#ifdef FLOW_TYPE_FLOWS
    const bit<8> flow_type = flow_types_t.FLOWS;
#elif defined(FLOW_TYPE_BIFLOWS)
    const bit<8> flow_type = flow_types_t.BIFLOWS;
#endif

const bit<32> MIRROR_SESSION_ID  = 99;

enum bit<8> flow_export_reasons_t {
    ACTIVE_TIMEOUT_HIT      = 0,
    INACTIVE_TIMEOUT_HIT    = 1,
    TCP_CONNECTION_FINISHED = 2,
    EXPORT_TRIGGERED        = 3,
    UNCERTAIN_CLASSIFIED    = 4
}



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

#define MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH 2  // defined with preprocessor declaration

#define FLOW_MONITORING_VALUE_WIDTH_EXTENDED (FLOW_MONITORING_VALUE_WIDTH + MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH + 1)
#define FLOW_MONITORING_TIMESTAMP_WIDTH_EXTENDED (FLOW_MONITORING_TIMESTAMP_WIDTH + MOVING_AVERAGE_WEIGHT_SHIFT_WIDTH + 1)

#endif  // __DEFINE__
