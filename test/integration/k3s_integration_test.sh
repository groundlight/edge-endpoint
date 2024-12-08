# first do basic pytest integration style tests
poetry run pytest -m live

poetry run python test/integration/submit_many_image_queries.py -n 1