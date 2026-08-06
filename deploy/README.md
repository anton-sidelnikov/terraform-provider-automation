# Kubernetes deployment

Generation, review, repair, and publishing run only through the local CLI. These manifests deploy the credential-free stateless planning, health, and metrics API used by remote clients and online evaluation. The image contains no Copilot runtime and the pod has no outbound network access.

1. Push a version tag matching `pyproject.toml`. `.github/workflows/release.yml` publishes local CLI distributions and a signed planning API image.
2. Replace the image tag in `deployment.yaml` with the released immutable digest (`image@sha256:...`).
3. Adjust the ingress-controller namespace in `network-policy.yaml`.
4. Apply the base:

   ```bash
   kubectl apply -k deploy
   ```

5. Copy `ingress.example.yaml`, set a real hostname/TLS secret, and apply it separately.
6. Configure the public HTTPS URL as `OTC_AGENT_EVAL_URL` in the `online-evaluation` environment. Apply ingress authentication externally if the endpoint must not be public.

The deployed API receives no GitHub, Copilot, model-provider, or cloud credential. Local publishing credentials never enter the cluster or GitHub Actions.
