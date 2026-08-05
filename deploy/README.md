# Kubernetes deployment

PR generation runs in isolated GitHub Actions jobs and does not require a long-lived model service. These manifests deploy the stateless planning/health/metrics API used by online evaluation.

1. Publish a signed release image with `.github/workflows/release.yml`.
2. Replace the image tag in `deployment.yaml` with the released immutable digest (`image@sha256:...`).
3. Adjust the ingress-controller namespace in `network-policy.yaml`.
4. Apply the base:

   ```bash
   kubectl apply -k deploy
   ```

5. Copy `ingress.example.yaml`, set a real hostname/TLS secret, and apply it separately.
6. Configure the public HTTPS URL as `OTC_AGENT_EVAL_URL` in the `online-evaluation` environment.

The deployed API receives no GitHub App private key or model credential. Publishing tokens are minted only inside protected GitHub Actions publisher jobs.

