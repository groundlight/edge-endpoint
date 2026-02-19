## Context

Your task is to improve the throughput of the Groundlight Edge Endpoint by optimizing any part of the stack to achieve higher throughput.

**Current Baseline**: 15-20 RPS
**Target**: 30+ RPS (preferably as high as possible)

**Primary Focus Area**: The inference server in zuuul is the suspected bottleneck where most time is spent (expensive operations happen here). Consider radical changes like rewriting in Rust or using alternative inference libraries.

Relevant parts of the stack are:
1) The inference server container, which is not defined in the edge-endpoint repo, but rather in zuuul (/home/tim/git/zuuul)
2) the helm deployment files (helm yamls etc.). There are located in /home/tim/git/edge-endpoint; you should be able to find the relevant files. 
3) The edge endpoint container itself (/home/tim/git/edge-endpoint/Dockerfile)

You will iteratively follow the instructions below and record your findings until you find a solution that materially improves performance. 

## SETUP
Read `agent_findings.txt` (if exists) to learn what has already been tried (if anything). Create the file if it doesn't already exist.

## TESTING

**IMPORTANT - NAMESPACE CLARIFICATION:**
- The Helm release is deployed in the `default` namespace (use `-n default` for helm commands)
- The actual application pods run in the `edge` namespace (use `-n edge` for kubectl commands)
- Always use `helm -n default` and `kubectl -n edge`

Uninstall the release each time you want to make a change. This ensures you are starting with a clean slate.
```sh
helm uninstall -n default edge-endpoint --wait
```

Make whatever code changes you think will improve 
   1) request throughput (we should see a steady RPS of more that 30 RPS, preferably as high as possible)


Write to `agent_findings.txt` about what you are about to try. For example:
```
Iteration 3 – 2025-11-19 11:54
Change: (What you are about to try, e.g. "Implement micro-batching to improve throughput")
```

If you have made changes to the inference server in zuuul, build it like this:
```sh
sh /home/tim/git/zuuul/predictors/serving/scripts/build_local_image.sh
```

If you have made any changes to the edge-endpoint image, build it like this:
```sh
sh /home/tim/git/edge-endpoint/deploy/bin/build-local-edge-endpoint-image.sh
```

Redeploy like this
```sh
helm upgrade -i -n default edge-endpoint edge-endpoint/groundlight-edge-endpoint   \
    --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}"   \
    --set-file configFile=/home/tim/git/edge-endpoint/configs/edge-config.yaml   \
    --set inferenceTag=dev \
    --set edgeEndpointTag=dev   \
    --wait
```
***IMPORTANT only use inferenceTag=dev if you have made some changes and rebuilt the inferece server image and would like to test those changes otherwise omit that flag.
***IMPORTANT only use edgeEndpointTag=dev if you have made some changes and rebuilt the edge-endpoint image and would like to test those changes otherwise omit that flag.

If you have made any changes to the local helm chart and would like to test them, you can specify the path of the local chart like this:
```sh
helm upgrade -i -n default edge-endpoint /home/tim/git/edge-endpoint/deploy/helm/groundlight-edge-endpoint \
  --set groundlightApiToken="${GROUNDLIGHT_API_TOKEN}" \
  --set-file configFile=/home/tim/git/edge-endpoint/configs/edge-config.yaml \
  --wait
```

Remember to try to make as few changes at one time as possible (be a good engineer). Usually one change at a time is best. Sometimes you might need to make changes to both the Edge Endpoint and Inference server at the same time because the changes might depend on each other; that is okay. 

Make sure the edge-endpoint pod is ready after you did the redeploy (note: pods run in `edge` namespace even though helm is in `default`)
```sh
kubectl get pods -n edge
```

When ready, run the test
```sh
cd /home/tim/git/edge-endpoint/load-testing
uv run python multiple_client_throughput_test.py COUNT --requests-per-second 5 --time-between-ramp 15 --max-clients 8
```

There will be a directory created that contains the results of the test. It should be printed out for you. If you have any trouble finding it, raise your hand. Otherwise, analyze the results and see if we have improved anything, in particular the max steady rps.

At the end of each iteration, record your findings to `agent_findings.txt`. Add to the file, do not overwrite anything
If there are any changes worth saving, save them somehow (would a git stash be best?). Make note of how you are saving them.

```
Iteration 3 – 2025-11-19 11:54
Change: (What you are about to try, e.g. "Implement micro-batching to improve throughput")
Process: (the deployment, testing and evaluation steps followed)
Results: (How many RPS? How much GPU utilization?)
Verdict: (An overall pass/fail)
Agent: (what agent are you? e.g. ChatGPT5)
Stashed changes: (where you stashed any useful changes, if any)
```

Do a maximum of 10 iterations per runtime (i.e. ignore any iterations from previous runtimes). 

Do not stop and wait for feedback at the end of a single iteration, keep going, and keep logging your findings. 

## CONCLUSION
At the end write a conclusion to `agent_findings.txt`. Tell me if anything you tried worked, and what your recommendation is (if any)

