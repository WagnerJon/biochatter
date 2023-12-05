from unittest.mock import Mock, patch
from biochatter.prompts import BioCypherPromptEngine
import pytest
from .conftest import calculate_test_score, RESULT_FILES

FILE_PATH = next(
    (
        s
        for s in RESULT_FILES
        if "biocypher" in s and "query" in s and "generation" in s
    ),
    None,
)

MODEL_NAMES = [
    "gpt-3.5-turbo",
    "gpt-4",
]


@pytest.fixture(scope="module", params=MODEL_NAMES)
def prompt_engine(request):
    model_name = request.param
    return BioCypherPromptEngine(
        schema_config_or_info_path="test/test_schema_info.yaml",
        model_name=model_name,
    )


def test_entity_selection(prompt_engine):
    with patch("biochatter.prompts.GptConversation") as mock_gptconv:
        system_msg = "You have access to a knowledge graph that contains these entities: Protein, Gene, Disease. Your task is to select the ones that are relevant to the user's question for subsequent use in a query. Only return the entities, comma-separated, without any additional text. "
        mock_gptconv.return_value.query.return_value = ["Gene,Disease", Mock(), None]
        mock_append_system_messages = Mock()
        mock_gptconv.return_value.append_system_message = mock_append_system_messages
        success = prompt_engine._select_entities(
            question="Which genes are associated with mucoviscidosis?"
        )
        assert success
        mock_append_system_messages.assert_called_once_with((system_msg))

        score = []
        score.append("Gene" in prompt_engine.selected_entities)
        score.append("Disease" in prompt_engine.selected_entities)

        with open(FILE_PATH, "a") as f:
            f.write(
                f"{prompt_engine.model_name},entities,{calculate_test_score(score)}\n"
            )


def test_relationship_selection(prompt_engine):
    prompt_engine.question = "Which genes are associated with mucoviscidosis?"
    prompt_engine.selected_entities = ["Gene", "Disease"]
    with patch("biochatter.prompts.GptConversation") as mock_gptconv:
        mock_gptconv.return_value.query.return_value = ["GeneToPhenotypeAssociation", Mock(), None]
        mock_append_system_messages = Mock()
        mock_gptconv.return_value.append_system_message = mock_append_system_messages
        success = prompt_engine._select_relationships()
        assert success
        mock_append_system_messages.assert_called_once_with('You have access to a knowledge graph that contains these entities: Gene, Disease. Your task is to select the relationships that are relevant to the user\'s question for subsequent use in a query. Only return the relationships without their sources or targets, comma-separated, and without any additional text. Here are the possible relationships and their source and target entities: [["GeneToPhenotypeAssociation", ["Disease", "Protein"]], ["GeneToPhenotypeAssociation", ["Disease", "Gene"]]].')

        score = []
        score.append(
            prompt_engine.selected_relationships == ["GeneToPhenotypeAssociation"]
        )
        score.append(
            "PERTURBED" in prompt_engine.selected_relationship_labels.keys()
        )
        score.append(
            "source" in prompt_engine.selected_relationship_labels.get("PERTURBED")
        )
        score.append(
            "target" in prompt_engine.selected_relationship_labels.get("PERTURBED")
        )
        score.append(
            "Disease"
            in prompt_engine.selected_relationship_labels.get("PERTURBED").get(
                "source"
            )
        )
        score.append(
            "Protein"
            in prompt_engine.selected_relationship_labels.get("PERTURBED").get(
                "target"
            )
        )
    
        with open(FILE_PATH, "a") as f:
            f.write(
                f"{prompt_engine.model_name},relationships,{calculate_test_score(score)}\n"
            )


def test_property_selection(prompt_engine):
    prompt_engine.question = "Which genes are associated with mucoviscidosis?"
    prompt_engine.selected_entities = ["Gene", "Disease"]
    prompt_engine.selected_relationships = ["GeneToPhenotypeAssociation"]
    with patch("biochatter.prompts.GptConversation") as mock_gptconv:
        resultMsg = '''
        {
            "Disease":{
                "name":"mucoviscidosis"
            },
            "GeneToPhenotypeAssociation":{
                "score":null,
                "source":null,
                "evidence":null
            }
        }'''
        mock_gptconv.return_value.query.return_value = [resultMsg, Mock(), None]
        mock_append_system_messages = Mock()
        mock_gptconv.return_value.append_system_message = mock_append_system_messages
        success = prompt_engine._select_properties()
        assert success
        mock_append_system_messages.assert_called_once_with("You have access to a knowledge graph that contains entities and relationships. They have the following properties. Entities:{'Disease': ['name', 'ICD10', 'DSM5']}, Relationships: {'GeneToPhenotypeAssociation': ['score', 'source', 'evidence']}. Your task is to select the properties that are relevant to the user's question for subsequent use in a query. Only return the entities and relationships with their relevant properties in JSON format, without any additional text. Return the entities/relationships as top-level dictionary keys, and their properties as dictionary values. Do not return properties that are not relevant to the question.")

        score = []
        score.append("Disease" in prompt_engine.selected_properties.keys())
        score.append("name" in prompt_engine.selected_properties.get("Disease"))

        with open(FILE_PATH, "a") as f:
            f.write(
                f"{prompt_engine.model_name},properties,{calculate_test_score(score)}\n"
            )


def test_query_generation(prompt_engine):
    with patch("biochatter.prompts.GptConversation") as mock_gptconv:
        resultMsg = '''
        MATCH (d:Disease {name: 'mucoviscidosis'})-[:PERTURBED]->(g:Gene)
        RETURN g.name AS AssociatedGenes
        '''
        mock_gptconv.return_value.query.return_value = [resultMsg, Mock(), None]
        mock_append_system_messages = Mock()
        mock_gptconv.return_value.append_system_message = mock_append_system_messages
        query = prompt_engine._generate_query(
            question="Which genes are associated with mucoviscidosis?",
            entities=["Gene", "Disease"],
            relationships={
                "PERTURBED": {"source": "Disease", "target": ["Protein", "Gene"]}
            },
            properties={"Disease": ["name", "ICD10", "DSM5"]},
            query_language="Cypher",
        )
        mock_append_system_messages.assert_called_once_with("Generate a database query in Cypher that answers the user's question. You can use the following entities: ['Gene', 'Disease'], relationships: ['PERTURBED'], and properties: {'Disease': ['name', 'ICD10', 'DSM5']}. Given the following valid combinations of source, relationship, and target: '(:Disease)-(:PERTURBED)->(:Protein)', '(:Disease)-(:PERTURBED)->(:Gene)', generate a Cypher query using one of these combinations. Only return the query, without any additional text.")
        score = []
        score.append("MATCH" in query)
        score.append("RETURN" in query)
        score.append("Gene" in query)
        score.append("Disease" in query)
        score.append("mucoviscidosis" in query)
        score.append(
            (
                "-[:PERTURBED]->(g:Gene)" in query
                or "(g:Gene)<-[:PERTURBED]-" in query
            )
        )
        score.append("WHERE" in query or "{name:" in query)
    
        with open(FILE_PATH, "a") as f:
            f.write(
                f"{prompt_engine.model_name},cypher query,{calculate_test_score(score)}\n"
            )

@pytest.mark.skip(reason="temporarily skip")
def test_end_to_end_query_generation(prompt_engine):
    query = prompt_engine.generate_query(
        question="Which genes are associated with mucoviscidosis?",
        query_language="Cypher",
    )

    score = []
    score.append("MATCH" in query)
    score.append("RETURN" in query)
    score.append("Gene" in query)
    score.append("Disease" in query)
    score.append("mucoviscidosis" in query)
    score.append(
        (
            "-[:PERTURBED]->(g:Gene)" in query
            or "(g:Gene)<-[:PERTURBED]-" in query
        )
    )
    score.append("WHERE" in query or "{name:" in query)

    with open(FILE_PATH, "a") as f:
        f.write(
            f"{prompt_engine.model_name},end-to-end,{calculate_test_score(score)}\n"
        )
