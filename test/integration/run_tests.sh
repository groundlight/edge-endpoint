# first do basic pytest integration style tests
# we skip the async test because we're setup for edge answers
if ! poetry run pytest -m live -k "not test_post_image_query_via_sdk_want_async"; then
    echo "Error: pytest integration tests failed."
    exit 1
fi

echo "Submitting image queries from the edge"

poetry run python test/integration/integration_test.py -m initial -d $DETECTOR_ID

# echo "Sleeping for 1 minute to allow deployment to get created..."
# sleep 60
# echo "Waiting for the deployment to rollout (inferencemodel-$detector_id)"

# if ! kubectl wait --for=condition=ready pod -l app=inferencemodel-$detector_id -n $DEPLOYMENT_NAMESPACE --timeout=2m; then
#     echo "Error: inference model for detector $detector_id pods failed to become ready within the timeout period."
#     exit 1
# fi

# echo "Inference model for detector $detector_id has successfully rolled out"