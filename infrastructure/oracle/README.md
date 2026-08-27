# Oracle Cloud Deployment

Full step-by-step is in `docs/DEPLOYMENT.md`; this file is the
Oracle-specific reference kept next to any Oracle config files.

## No Terraform included — here's why
Oracle Cloud's Always Free tier provisioning (VCN, subnet, security
lists, the A1 Ampere instance itself) is a one-time setup done through
the OCI Console or CLI. A Terraform module was considered but **not
included**, for two honest reasons:
1. It cannot be tested against a live Oracle tenancy in the environment
   that generated this repo (no account access).
2. Always Free capacity allocation is region/tenancy-specific and prone
   to "out of capacity" errors that a Terraform apply doesn't handle
   gracefully — the manual Console flow lets you retry across
   availability domains, which matters more for Always Free than for
   paid capacity.

If you want to automate this yourself, `oci-terraform-provider`
(`hashicorp/oci`) is the real provider to use — this is not fabricated
guidance, but actually writing and testing the module is left to you.

## Manual setup (verified against current OCI Console flow)
1. **Compute → Instances → Create Instance**
   - Image: Ubuntu 22.04 or later (Minimal)
   - Shape: `VM.Standard.A1.Flex`, 2 OCPU / 12GB (confirm your current
     Always Free ceiling in the shape picker — Oracle has changed this
     before)
   - Boot volume: 100GB
2. **Networking → Virtual Cloud Networks → Create VCN with Internet
   Connectivity** (use the wizard — it creates the public subnet,
   internet gateway, and route table for you)
3. **Security List** (on the public subnet): allow inbound 22/tcp from
   your IP only. Do NOT open 443 if you're using Cloudflare Tunnel
   (see `infrastructure/cloudflare/`) — the tunnel needs no inbound rule.
4. SSH in, then run the automated bootstrap:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/<you>/agent-os/main/infrastructure/oracle/bootstrap.sh | bash
   # log out/in for docker group membership, then:
   git clone <your-repo-url> && cd agent-os
   cp .env.example .env && nano .env
   ./scripts/setup.sh
   ./scripts/deploy.sh
   ```
   `bootstrap.sh` automates what was previously manual steps here:
   swap file creation, ufw firewall (deny-by-default, SSH-only inbound),
   Docker Engine + Buildx + Compose plugin from Docker's official APT repository,
   Docker daemon enable/start, bounded daemon logs, git install, and the Docker
   hello-world smoke test. The Docker installation is shared with
   `infrastructure/docker/install-docker.sh`.

## Known Always Free gotcha
Oracle has previously reduced Always Free ARM allocation without much
notice (2 OCPU/12GB as of mid-2026, down from 4 OCPU/24GB). Check your
current tenancy's actual limit in Console → Governance → Limits, Quotas
and Usage before assuming 12GB — resize your resource budget in
`docker-compose.yml`'s `deploy.resources.limits` accordingly if yours
differs.

## Docker host standard

The bootstrap uses Docker's official APT repository rather than the convenience
installation script. It installs Docker Engine, CLI, containerd, Buildx and the
Compose plugin; enables the Docker/containerd systemd services; verifies the
daemon with `docker version`; and runs `hello-world`. This is the preferred
production path for the Ubuntu VPSs targeted by this repository.

For a non-Oracle Ubuntu VPS such as Contabo, the same Docker host bootstrap is
available at `infrastructure/docker/bootstrap-ubuntu.sh`.
