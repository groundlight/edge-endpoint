# first do basic pytest integration style tests
# we skip the async test because we're setup for edge answers
if ! poetry run pytest -m live -k "not test_post_image_query_via_sdk_want_async"; then
    echo "Error: pytest integration tests failed."
    exit 1
fi

echo "Submitting image queries from the edge"

echo "Submitting initial iqs, ensuring we get low confidence at first"
# submit initial tests that we get low confidence answers at first
poetry run python test/integration/integration_test.py -m initial -d $DETECTOR_ID

echo "Training detector in the cloud"
# now we improve the model by submitting many iqs and labels
poetry run python test/integration/integration_test.py -m improve_model -d $DETECTOR_ID

echo "Now we sleep for $REFRESH_RATE seconds to get a newer model" 
sleep $REFRESH_RATE
echo "Ensuring a new pod for the deployment $DETECTOR_ID_WITH_DASHES has been created in the last $REFRESH_RATE seconds..."

# Ensure our most recent pod is brand new
most_recent_pod=$(kubectl get pods -n $DEPLOYMENT_NAMESPACE -l app=inference-server -o jsonpath='{.items[-1].metadata.name}')
current_time=$(date +%s)
pod_creation_time=$(kubectl get pod $most_recent_pod -n $DEPLOYMENT_NAMESPACE -o jsonpath='{.metadata.creationTimestamp}')
pod_creation_time_seconds=$(date -d "$pod_creation_time" +%s)
time_difference=$((current_time - pod_creation_time_seconds))

# Check if the pod was created within 1.1 times the refresh rate
if [ $time_difference -le $(echo "$REFRESH_RATE * 1.1" | bc) ]; then
    echo "A new pod for the deployment $DETECTOR_ID_WITH_DASHES has been created within 1.1 times the refresh rate."
else
    echo "Error: No new pod for the deployment $DETECTOR_ID_WITH_DASHES has been created within 1.1 times the refresh rate."
    exit 1
fi