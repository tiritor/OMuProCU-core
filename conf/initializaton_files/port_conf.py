
# This is a dict for nexthops and LAG/ECMP configuration
nexthops = {
    "np_1" : {
        "mbr_base": 200000,
        "dp_ports": {
            44: True,
            144: True
        },
    },
    "np_2": {
        "mbr_base": 100000,
        "dp_ports": {
            145: True
        },
    }
}

DEFAULT_PORTS = {
    "stordis-01" : {
        17 : {
            "id" : "17/0",
            "dp": 44,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        18 : {
            "id" : "18/0",
            "dp": 45,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        33 : {
            "id" : "33/0",
            "dp": 144,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        34 : {
            "id" : "34/0",
            "dp": 145,
            "speed": "10G",
            "fec": "NONE",
            "enabled": True
        }
    },
    "stordis-02" : {
        17 : {
            "id" : "17/0",
            "dp": 44,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        18 : {
            "id" : "18/0",
            "dp": 45,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
    },
    "stordis-03" : {
        17 : {
            "id" : "17/0",
            "dp": 44,
            "speed": "25G",
            "fec": "RS",
            "enabled": False
        },
        18 : {
            "id" : "18/0",
            "dp": 45,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        33 : {
            "id" : "33/0",
            "dp": 144,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        34 : {
            "id" : "34/0",
            "dp": 145,
            "speed": "10G",
            "fec": "NONE",
            "enabled": True
        }
    },
    "stordis-04" : {
        17 : {
            "id" : "17/0",
            "dp": 44,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        18 : {
            "id" : "18/0",
            "dp": 45,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        33 : {
            "id" : "33/0",
            "dp": 144,
            "speed": "25G",
            "fec": "RS",
            "enabled": True
        },
        34 : {
            "id" : "34/0",
            "dp": 145,
            "speed": "10G",
            "fec": "NONE",
            "enabled": True
        }
    },
}
