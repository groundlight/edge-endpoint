from typing import Any

import pytest
from model import (
    BinaryClassificationResult,
    BoundingBoxResult,
    CountingResult,
    Label,
    ModeEnum,
    MultiClassificationResult,
    ResultTypeEnum,
    Source,
    ROI,
    BBoxGeometry,
)

from app.core.utils import (
    METADATA_SIZE_LIMIT_BYTES,
    ModelInfoBase,
    ModelInfoNoBinary,
    ModelInfoWithBinary,
    _size_of_dict_in_bytes,
    create_iq,
    generate_metadata_dict,
    parse_model_info,
    prefixed_ksuid,
)


class TestGenerateMetadataDict:
    def setup_method(self):
        pass

    @pytest.fixture
    def basic_binary_result(self):
        return {
            "confidence": 0.84,
            "label": 1,
            "text": None,
            "rois": None,
            "raw_primary_confidence": 0.84,
            "raw_oodd_prediction": {"confidence": 1.0, "label": 0.0, "text": None, "rois": None},
        }

    @pytest.fixture
    def basic_count_result(self):
        return {
            "confidence": 0.08,
            "label": 1,
            "text": None,
            "rois": [
                {
                    "label": "bird",
                    "geometry": {
                        "left": 0.40,
                        "top": 0.40,
                        "right": 0.60,
                        "bottom": 0.60,
                        "version": "2.0",
                        "x": 0.50,
                        "y": 0.50,
                    },
                    "score": 0.80,
                    "version": "2.0",
                }
            ],
            "raw_primary_confidence": 0.08,
            "raw_oodd_prediction": {"confidence": 1.0, "label": 0.0, "text": None, "rois": None},
        }

    @pytest.fixture
    def many_rois_count_result(self):
        return {
            "confidence": 0.08,
            "label": 10,
            "text": None,
            "rois": [
                {
                    "label": "bird",
                    "geometry": {
                        "left": 0.40,
                        "top": 0.40,
                        "right": 0.60,
                        "bottom": 0.60,
                        "version": "2.0",
                        "x": 0.50,
                        "y": 0.50,
                    },
                    "score": 0.80,
                    "version": "2.0",
                }
            ]
            * 10,  # contains 10 ROI objects
            "raw_primary_confidence": 0.08,
            "raw_oodd_prediction": {"confidence": 1.0, "label": 0.0, "text": None, "rois": None},
        }

    @pytest.fixture
    def count_result_with_too_large_text(self):
        return {
            "confidence": 0.08,
            "label": 10,
            "text": "a" * METADATA_SIZE_LIMIT_BYTES,  # The text field will cause the size limit to be exceeded.
            "rois": [
                {
                    "label": "bird",
                    "geometry": {
                        "left": 0.40,
                        "top": 0.40,
                        "right": 0.60,
                        "bottom": 0.60,
                        "version": "2.0",
                        "x": 0.50,
                        "y": 0.50,
                    },
                    "score": 0.80,
                    "version": "2.0",
                }
            ]
            * 10,
            "raw_primary_confidence": 0.08,
            "raw_oodd_prediction": {"confidence": 1.0, "label": 0.0, "text": None, "rois": None},
        }

    def _assert_metadata_within_size_limit(self, metadata: dict[str, Any]):
        assert _size_of_dict_in_bytes(metadata) < METADATA_SIZE_LIMIT_BYTES

    def test_metadata_dict_no_results(self):
        """Test generating metadata without providing a response dict."""
        metadata = generate_metadata_dict(results=None)
        expected_metadata = {"edge_result": None}
        assert metadata == expected_metadata

        metadata = generate_metadata_dict(results=None, is_edge_audit=True)
        expected_metadata = {"edge_result": None, "is_edge_audit": True}
        assert metadata == expected_metadata

    def test_basic_binary_metadata_dict(self, basic_binary_result: dict[str, Any]):
        """Test generating metadata for a simple binary response."""
        metadata = generate_metadata_dict(results=basic_binary_result)
        expected_metadata = {"edge_result": basic_binary_result}

        assert metadata == expected_metadata
        self._assert_metadata_within_size_limit(metadata)

    def test_binary_metadata_dict_with_audit(self, basic_binary_result: dict[str, Any]):
        """Test generating metadata for a simple binary response which is also an edge audit."""
        metadata = generate_metadata_dict(results=basic_binary_result, is_edge_audit=True)
        expected_metadata = {"edge_result": basic_binary_result, "is_edge_audit": True}

        assert metadata == expected_metadata
        self._assert_metadata_within_size_limit(metadata)

    def test_basic_count_metadata_dict(self, basic_count_result: dict[str, Any]):
        """Test generating metadata for a simple count response."""
        metadata = generate_metadata_dict(results=basic_count_result)
        expected_metadata = {"edge_result": basic_count_result}

        assert metadata == expected_metadata
        self._assert_metadata_within_size_limit(metadata)

    def test_count_metadata_dict_many_rois_with_audit(self, many_rois_count_result: dict[str, Any]):
        "Test generating metadata for a count response with many ROIs that will exceed the size limit."
        metadata = generate_metadata_dict(results=many_rois_count_result, is_edge_audit=True)
        modified_results = many_rois_count_result.copy()
        modified_results["rois"] = f"{len(many_rois_count_result['rois'])} ROIs were detected."
        expected_metadata = {"edge_result": modified_results, "is_edge_audit": True}

        assert metadata == expected_metadata
        self._assert_metadata_within_size_limit(metadata)

    def test_results_exceed_without_rois(self, count_result_with_too_large_text: dict[str, Any]):
        "Test generating metadata for a count response which exceeds the size limit even when ROIs are removed."
        metadata = generate_metadata_dict(results=count_result_with_too_large_text)
        expected_metadata = {}  # Should not include the results at all

        assert metadata == expected_metadata
        self._assert_metadata_within_size_limit(metadata)


class TestCreateIQ:
    def setup_method(self):
        self.confidence_threshold = 0.75

    def test_create_binary_iq(self):
        """Test creating a basic binary IQ."""
        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.BINARY,
            mode_configuration=None,
            result_value=0,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert "iq_" in iq.id
        assert iq.result_type == ResultTypeEnum.binary_classification
        assert isinstance(iq.result, BinaryClassificationResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.label == Label.YES
        assert "is_from_edge" in iq.metadata
        assert iq.metadata["is_from_edge"]

    def test_create_count_iq(self):
        """Test creating a basic count IQ."""
        count_value = 2
        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.COUNT,
            mode_configuration={"max_count": 5, "class_name": "test_class"},
            result_value=count_value,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert "iq_" in iq.id
        assert iq.result_type == ResultTypeEnum.counting
        assert isinstance(iq.result, CountingResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.count == count_value
        assert not iq.result.greater_than_max
        assert "is_from_edge" in iq.metadata
        assert iq.metadata["is_from_edge"]

    def test_create_count_iq_greater_than_max(self):
        """Test creating a count IQ with count greater than the max count."""
        count_value = 6
        max_count_value = 5
        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.COUNT,
            mode_configuration={"max_count": max_count_value, "class_name": "test_class"},
            result_value=count_value,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert iq.result_type == ResultTypeEnum.counting
        assert isinstance(iq.result, CountingResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.greater_than_max
        assert iq.result.count == max_count_value

    def test_create_multiclass_iq(self):
        """Test creating a basic multiclass IQ."""

        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.MULTI_CLASS,
            mode_configuration={"class_names": ["1", "2", "3"]},
            result_value=0,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert "iq_" in iq.id
        assert iq.result_type == ResultTypeEnum.multi_classification
        assert isinstance(iq.result, MultiClassificationResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.label == "1"
        assert "is_from_edge" in iq.metadata
        assert iq.metadata["is_from_edge"]

    def test_create_bounding_box_iq(self):
        """Test creating a basic bounding box IQ."""
        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.BOUNDING_BOX,
            mode_configuration={"max_num_bboxes": 5, "class_name": "test_class"},
            result_value="BOUNDING_BOX",
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
            rois=[
                ROI(
                    label="test_class",
                    score=0.8,
                    geometry=BBoxGeometry(left=0.4, top=0.4, right=0.6, bottom=0.6),
                )
            ],
        )

        assert "iq_" in iq.id
        assert iq.result_type == ResultTypeEnum.bounding_box
        assert isinstance(iq.result, BoundingBoxResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.label == "BOUNDING_BOX"
        assert iq.rois == [
            ROI(
                label="test_class",
                score=0.8,
                geometry=BBoxGeometry(left=0.4, top=0.4, right=0.6, bottom=0.6),
            )
        ]
        assert "is_from_edge" in iq.metadata
        assert iq.metadata["is_from_edge"]

    def test_create_count_iq_without_configuration(self):
        """Test creating a count IQ with no mode_configuration."""
        with pytest.raises(ValueError, match="mode_configuration for Counting detector shouldn't be None."):
            create_iq(
                detector_id=prefixed_ksuid("det_"),
                mode=ModeEnum.COUNT,
                mode_configuration=None,
                result_value=1,
                confidence=0.8,
                confidence_threshold=self.confidence_threshold,
                query="Test query",
            )

    def test_create_multiclass_iq_without_configuration(self):
        """Test creating a multiclass IQ with no mode_configuration."""
        with pytest.raises(ValueError, match="mode_configuration for MultiClass detector shouldn't be None."):
            create_iq(
                detector_id=prefixed_ksuid("det_"),
                mode=ModeEnum.MULTI_CLASS,
                mode_configuration=None,
                result_value=1,
                confidence=0.8,
                confidence_threshold=self.confidence_threshold,
                query="Test query",
            )

    def test_create_bounding_box_iq_without_configuration(self):
        """Test creating a bounding box IQ with no mode_configuration."""
        with pytest.raises(ValueError, match="mode_configuration for Bounding Box detector shouldn't be None."):
            create_iq(
                detector_id=prefixed_ksuid("det_"),
                mode=ModeEnum.BOUNDING_BOX,
                mode_configuration=None,
                result_value="BOUNDING_BOX",
                confidence=0.8,
                confidence_threshold=self.confidence_threshold,
                query="Test query",
                rois=[
                    ROI(
                        label="test_class",
                        score=0.8,
                        geometry=BBoxGeometry(left=0.4, top=0.4, right=0.6, bottom=0.6),
                    )
                ],
            )


class TestParseModelInfo:
    def test_parse_with_binary(self):
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
            "model_binary_id": "test_binary_id",
            "model_binary_url": "test_binary_url",
            "oodd_pipeline_config": "test_oodd_pipeline_config",
            "oodd_model_binary_id": "test_oodd_binary_id",
            "oodd_model_binary_url": "test_oodd_binary_url",
        }
        primary_edge_model_info, oodd_model_info = parse_model_info(model_info)

        assert isinstance(primary_edge_model_info, ModelInfoBase)
        assert isinstance(primary_edge_model_info, ModelInfoWithBinary)
        assert isinstance(oodd_model_info, ModelInfoBase)
        assert isinstance(oodd_model_info, ModelInfoWithBinary)

    def test_parse_no_binary(self):
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
            "model_binary_id": None,
            "model_binary_url": None,
            "oodd_pipeline_config": "test_oodd_pipeline_config",
            "oodd_model_binary_id": None,
            "oodd_model_binary_url": None,
        }
        primary_edge_model_info, oodd_model_info = parse_model_info(model_info)

        assert isinstance(primary_edge_model_info, ModelInfoBase)
        assert isinstance(primary_edge_model_info, ModelInfoNoBinary)
        assert isinstance(oodd_model_info, ModelInfoBase)
        assert isinstance(oodd_model_info, ModelInfoNoBinary)

        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
            "oodd_pipeline_config": "test_oodd_pipeline_config",
        }
        primary_edge_model_info, oodd_model_info = parse_model_info(model_info)

        assert isinstance(primary_edge_model_info, ModelInfoBase)
        assert isinstance(primary_edge_model_info, ModelInfoNoBinary)
        assert isinstance(oodd_model_info, ModelInfoBase)
        assert isinstance(oodd_model_info, ModelInfoNoBinary)

    def test_parse_one_binary(self):
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
            "model_binary_id": "test_binary_id",
            "model_binary_url": "test_binary_url",
            "oodd_pipeline_config": "test_oodd_pipeline_config",
        }
        primary_edge_model_info, oodd_model_info = parse_model_info(model_info)

        assert isinstance(primary_edge_model_info, ModelInfoBase)
        assert isinstance(primary_edge_model_info, ModelInfoWithBinary)
        assert isinstance(oodd_model_info, ModelInfoBase)
        assert isinstance(oodd_model_info, ModelInfoNoBinary)

        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
            "oodd_pipeline_config": "test_oodd_pipeline_config",
            "oodd_model_binary_id": "test_oodd_binary_id",
            "oodd_model_binary_url": "test_oodd_binary_url",
        }
        primary_edge_model_info, oodd_model_info = parse_model_info(model_info)

        assert isinstance(primary_edge_model_info, ModelInfoBase)
        assert isinstance(primary_edge_model_info, ModelInfoNoBinary)
        assert isinstance(oodd_model_info, ModelInfoBase)
        assert isinstance(oodd_model_info, ModelInfoWithBinary)
