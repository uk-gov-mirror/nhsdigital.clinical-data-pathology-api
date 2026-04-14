@status_merged_auth_headers
@remote_only
Feature: pathology Bundle API
  As an API consumer
  I want to interact with the pathology API
  So that I can verify it responds correctly to valid and invalid requests

  Background: The API is running
    Given the API is running

  Scenario: Send a valid Bundle
    When I send a valid Bundle to the Pathology API
    Then the response status code should be 200
    And the response should contain a valid "document" Bundle
    And the response should include the created test result

  Scenario: Sending an invalid bundle
    When I send an invalid Bundle to the Pathology API
    Then the response status code should be 400

  Scenario: Send a bundle with missing Composition
    When I send a Bundle with missing Composition to the Pathology API
    Then the response status code should be 400

  Scenario: Send a bundle with incorrect bundle type
    When I send a Bundle with type "transaction" to the Pathology API
    Then the response status code should be 400
