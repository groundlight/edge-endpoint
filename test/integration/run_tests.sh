# This script runs integration tests, assuming k3s and detector setup via setup_and_run_tests.sh.
# Run all tests with: > make test-with-k3s
# It combines Python (for image submission) and Bash (for k3s checks).
# The test includes:
# 1) Running pytest live tests for health, readiness, and image submission to the edge.
# 2) Submitting an image to the edge using a cat/dog detector, 
#   checking for low confidence, training the edge detector via cloud escalation, and 
#   verifying model improvement in a new edge pod.

set -e

# first do basic pytest integration style tests
# we skip the async test because we're setup for edge answers
if ! uv run pytest -m live -k "not test_post_image_query_via_sdk_want_async"; then
    echo "Error: pytest integration tests failed."
    exit 1
fi

echo "Submitting initial iqs, ensuring we get low confidence at first"
# submit initial tests that we get low confidence answers at first
uv run python test/integration/integration.py -m initial -d $DETECTOR_ID

echo "Getting current inference pod creation time before training in the cloud..."
# Get the creation time of the current inference pod before training
most_recent_pod_before_training=$(kubectl get pods -n $DEPLOYMENT_NAMESPACE -l app=inference-server -o jsonpath='{.items[-1].metadata.name}')
pod_creation_time_before_training=$(kubectl get pod $most_recent_pod_before_training -n $DEPLOYMENT_NAMESPACE -o jsonpath='{.metadata.creationTimestamp}')
pod_creation_time_seconds_before_training=$(date -d "$pod_creation_time_before_training" +%s)

echo "Training detector in the cloud"
# now we improve the model by submitting many iqs and labels
uv run python test/integration/integration.py -m improve_model -d $DETECTOR_ID

# Poll for a new inference pod to appear with creationTimestamp newer than the
# pre-training pod, then wait for it to become Ready. Replaces a flat
# `sleep $((4 * REFRESH_RATE))` that always burned 240s of idle time even
# though the refresh typically completes in 60-90s.
echo "Polling for refreshed inference pod (timeout $((5 * REFRESH_RATE))s)..."
poll_end=$(($(date +%s) + 5 * REFRESH_RATE))
new_pod=""
while [ $(date +%s) -lt $poll_end ]; do
    candidate=$(kubectl get pods -n $DEPLOYMENT_NAMESPACE -l app=inference-server \
                --sort-by=.metadata.creationTimestamp \
                -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null || true)
    if [ -n "$candidate" ] && [ "$candidate" != "$most_recent_pod_before_training" ]; then
        candidate_time=$(kubectl get pod $candidate -n $DEPLOYMENT_NAMESPACE \
                         -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null || true)
        if [ -n "$candidate_time" ]; then
            candidate_time_seconds=$(date -d "$candidate_time" +%s)
            if [ $candidate_time_seconds -gt $pod_creation_time_seconds_before_training ]; then
                new_pod=$candidate
                break
            fi
        fi
    fi
    sleep 5
done

if [ -z "$new_pod" ]; then
    echo "Error: No new pod for the deployment $DETECTOR_ID_WITH_DASHES has been created after training."
    exit 1
fi
echo "A new pod for the deployment $DETECTOR_ID_WITH_DASHES has been created after training: $new_pod"

echo "Waiting for new pod $new_pod to become Ready..."
kubectl wait --for=condition=Ready pod/$new_pod -n $DEPLOYMENT_NAMESPACE --timeout=2m

# NOTE this is temporarily reworded because the current implementation of OODD makes this unreliable.
# echo Now we check if the edge model performs well...
echo Now we check that we can submit queries to the new inference pod...
uv run python test/integration/integration.py -m final -d $DETECTOR_ID

echo Now checking that the edge metrics status page is available...
uv run python test/integration/status.py

echo All tests pass :D
