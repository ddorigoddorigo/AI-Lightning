#!/bin/bash
MAC=$(xxd -p /home/ubuntu/.lnd/data/chain/bitcoin/testnet/admin.macaroon | tr -d "\n")
curl -s --insecure -H "Grpc-Metadata-macaroon: $MAC" https://localhost:8080/v1/invoices | python3 -m json.tool | tail -100
