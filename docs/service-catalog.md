# Service-to-documentation mapping

## Decision

Do not derive documentation repository names from abbreviations at run time. Keep a reviewed, versioned mapping in `config/services.json`, and separately discover which organization repositories contain the canonical `api-ref/source/index.rst` marker. A mapping is valid only if its documentation slug is in that eligibility snapshot.

This resolves the naming mismatch without unsafe guessing:

- an exact unique routing key or SDK abbreviation wins; provider names, docs slugs, and reviewed aliases resolve only when unambiguous;
- normalization is limited to case, spaces, underscores, and repeated hyphens;
- fuzzy matching produces suggestions in an error only—it never selects a source;
- an override must equal the reviewed mapping and be api-ref eligible;
- one-to-many services such as DMS Kafka/RabbitMQ/RocketMQ require explicit variant records before use;
- shared SDK packages or historical provider aliases need an explicit adapter record, not a naming heuristic.

The weekly catalog audit discovers active public repositories and checks the marker. Drift fails the workflow and produces a report containing both new repositories and api-ref repositories without a mapping. A maintainer then verifies ownership/API relevance and updates the eligibility snapshot in a normal PR. Discovery never silently changes production routing.

## Reviewed mapping

| SDK package / routing key | Provider path | Documentation repository | Service |
|---|---|---|---|
| `antiddos` | `antiddos` | `anti-ddos` | Anti-DDoS |
| `apigw` | `apigw` | `api-gateway` | API Gateway |
| `asm` | `asm` | `application-service-mesh` | Application Service Mesh |
| `autoscaling` | `as` | `auto-scaling` | Auto Scaling |
| `bms` | `bms` | `bare-metal-server` | Bare Metal Server |
| `cbr` | `cbr` | `cloud-backup-recovery` | Cloud Backup and Recovery |
| `cc` | `cc` | `cloud-connect` | Cloud Connect |
| `cce` | `cce` | `cloud-container-engine` | Cloud Container Engine |
| `cci` | `cci` | `cloud-container-instance` | Cloud Container Instance |
| `ces` | `ces` | `cloud-eye` | Cloud Eye |
| `cfw` | `cfw` | `cloud-firewall` | Cloud Firewall |
| `csbs` | `csbs` | `cloud-server-backup-service` | Cloud Server Backup Service |
| `css` | `css` | `cloud-search-service` | Cloud Search Service |
| `cts` | `cts` | `cloud-trace-service` | Cloud Trace Service |
| `dataarts` | `dataarts` | `data-arts-studio` | DataArts Studio |
| `dcaas` | `dcaas` | `direct-connect` | Direct Connect |
| `dcs` | `dcs` | `distributed-cache-service` | Distributed Cache Service |
| `ddm` | `ddm` | `distributed-database-middleware` | Distributed Database Middleware |
| `dds` | `dds` | `document-database-service` | Document Database Service |
| `deh` | `deh` | `dedicated-host` | Dedicated Host |
| `dms` | `dms` | `distributed-message-service` | Distributed Message Service |
| `dns` | `dns` | `domain-name-service` | Domain Name Service |
| `drs` | `drs` | `data-replication-service` | Data Replication Service |
| `dws` | `dws` | `data-warehouse-service` | Data Warehouse Service |
| `ecs` | `ecs` | `elastic-cloud-server` | Elastic Cloud Server |
| `elb` | `elb` | `elastic-load-balancing` | Elastic Load Balancing |
| `eps` | `eps` | `enterprise-project-service` | Enterprise Project Service |
| `er` | `er` | `enterprise-router` | Enterprise Router |
| `evs` | `evs` | `elastic-volume-service` | Elastic Volume Service |
| `fgs` | `fgs` | `function-graph` | FunctionGraph |
| `gaussdb` | `gaussdb` | `gaussdb-opengauss` | GaussDB(openGauss) |
| `gemini` | `gemini` | `geminidb` | GeminiDB |
| `hss` | `hss` | `host-security-service` | Host Security Service |
| `identity` | `iam` | `identity-access-management` | Identity and Access Management |
| `ims` | `ims` | `image-management-service` | Image Management Service |
| `kms` | `kms` | `key-management-service` | Key Management Service |
| `lts` | `lts` | `log-tank-service` | Log Tank Service |
| `mrs` | `mrs` | `mapreduce-service` | MapReduce Service |
| `objectstorage` | `obs` | `object-storage-service` | Object Storage Service |
| `rds` | `rds` | `relational-database-service` | Relational Database Service |
| `rms` | `rms` | `resource-management-service` | Resource Management Service |
| `rts` | `rts` | `resource-formation-service` | Resource Formation Service |
| `sdrs` | `sdrs` | `storage-disaster-recovery-service` | Storage Disaster Recovery Service |
| `sfs` | `sfs` | `scalable-file-service` | Scalable File Service |
| `sfs_turbo` / `sfs-turbo` | `sfs` | `scalable-file-service` | Scalable File Service Turbo |
| `smn` | `smn` | `simple-message-notification` | Simple Message Notification |
| `swr` | `swr` | `software-repository-container` | Software Repository for Container |
| `taurus` | `taurusdb` | `taurusdb` | TaurusDB |
| `tms` | `tms` | `tag-management-service` | Tag Management Service |
| `vbs` | `vbs` | `volume-backup-service` | Volume Backup Service |
| `vpc` | `vpc` | `virtual-private-cloud` | Virtual Private Cloud |
| `vpcep` | `vpcep` | `vpc-endpoint` | VPC Endpoint |
| `evpn` | `vpn` | `virtual-private-network` | Virtual Private Network |
| `waf` | `waf` | `web-application-firewall` | Web Application Firewall |
| `waf-premium` | `waf` | `web-application-firewall-dedicated` | Web Application Firewall Dedicated |

This table is an automation routing table, not a claim that every documentation API already has SDK/provider coverage. `config/services.json` is the machine-readable authority. The eligibility snapshot currently contains 83 repositories verified on 2026-08-05; only the subset with a reviewed SDK/provider relationship appears above.

## Adding a mapping

1. Confirm the repository is active and contains `api-ref/source/index.rst` on its protected default branch.
2. Confirm the actual SDK package and provider service directories; do not infer them from initials.
3. Decide whether the mapping is one-to-one or needs a variant key.
4. Add the record and only necessary aliases; run `make catalog-check` and tests.
5. Review for collisions and update this table/evaluation cases.
6. Let the scheduled online audit verify the external marker.

For a completely new service, do not add a guessed mapping. Add the verified repository to the eligibility snapshot, manually dispatch the workflow with that repository name, and let `service_discovery` produce an abbreviation/package proposal for human approval. Only after approval is the mapping committed and full SDK creation started; provider creation follows the merged SDK revision.
