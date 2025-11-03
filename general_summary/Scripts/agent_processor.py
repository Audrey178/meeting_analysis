import logging
from typing import List, Dict, Tuple
import ast
import json
from model_handler import ModelHandler
from utils import _clean_response,_normalise_feedback


class Agents:
    def __init__(self, client, model,log_base_path):
        self.client = client
        self.model = model
        self.log_base_path = log_base_path
        
    def expert_agent(self, summary_input: Dict, outline: List[str], feedback_prompt: str = "") -> str:
        """
        Generate summary following outline structure and using matched facts with context.
        """
        system_prompt = f"""
        You are an expert summarization agent tasked with creating a structured meeting summary.
        Your primary goal is to follow the outline exactly while using matched facts and their contexts 
        to provide detailed information for each outline point.

        CRITICAL CONSTRAINTS:
        - DO NOT add any information that is not present in the provided contexts
        - DO NOT hallucinate or infer information
        - ONLY use facts and contexts explicitly provided
        - Summary MUST be between 150-200 words
        - Follow outline structure exactly

        Key Requirements:
        1. Outline Adherence:
        - STRICTLY follow the provided outline structure
        - Each outline point must be addressed in order
        - Maintain the outline's hierarchical organization
        - Ensure all major sections are covered
        - Use ONLY provided facts and contexts
        
        2. Using Enhanced Context:
        For each outline point:
        a. Find relevant matched facts where:
            - Fact's category/type matches the outline point
            - Fact has supporting context
            - Fact's importance score is appropriate
        
        b. Use the matched fact's context effectively:
            - Use ONLY provided fact content and context
            - No additional interpretation or assumptions
            - Stay strictly within provided information
        
        3. Content Organization:
        For each outline section:
        a. Begin with high-importance matched facts (scores 8-10)
            - Include relevant context as provided
            - No additional inferences
        
        b. Support with medium-importance facts (scores 6-7)
            - Use only provided context
            - Keep within word limit
        
        c. Add context from lower-importance facts if needed
            - Only if space permits within word limit
            - No speculative connections

        4. Integration Guidelines:
        - Use ONLY provided facts and contexts
        - Make connections ONLY when explicitly supported
        - Skip outline points with no matching facts rather than speculate
        - Maintain word limit of 150-200 words

        5. Special Cases:
        a. If an outline point has no direct fact matches:
            - Skip if no relevant information available
            - DO NOT make assumptions or add information
            - Move to next outline point
        
        b. If multiple facts match an outline point:
            - Prioritize by importance_score
            - Stay within word limit
            - Use only provided connections

        Remember:
        - NEVER add information not in provided context
        - Skip points without supporting facts
        - Use only explicit connections
        - Keep summary between 150-200 words
        - Format as cohesive paragraphs that flow naturally
        - DO NOT use bullet points, headers, or numbered lists
        - Present as a smooth narrative that covers key points from the outline

        """

        user_prompt = f"""
        Generate a 150-200 word meeting summary that follows this outline exactly:
        {outline}

        Use ONLY these matched facts and their contexts to support each outline point:
        {summary_input['matched_information']}

        Consider these unmatched features ONLY where explicitly relevant:
        {summary_input['unmatched_features']}

        Previous Feedback (if any):
        {feedback_prompt}

        IMPORTANT:
        - Use ONLY provided information
        - NO hallucination or inference
        - Stay within 150-200 words    
        - Format as cohesive paragraphs that flow naturally
        - DO NOT use bullet points, headers, or numbered lists
        - Present as a smooth narrative that covers key points from the outline and Skip outline points without supporting facts

        """
        
        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(
            self.client, message, self.model, "Summary Generation",    
            category="Summary Generation", 
            log_base_path=self.log_base_path
            )            
        return response

    def checker_agent(self, summary_input: Dict, outline: List[str], generated_summary: str):
        """Check summary adherence to outline and constraints."""
        output_format = {
            "confidence_score": 90,
            "feedback": "Summary follows outline and uses provided facts correctly."
        }
        
        system_prompt = f"""
        You are a checker agent evaluating a meeting summary. Verify:

        1. Outline Adherence (40 points)
        - Each outline point is addressed in order
        - No points are skipped unless no matching facts exist
        - Information appears under correct outline sections
        - Maintains outline's hierarchical structure

        2. Content Accuracy (30 points)
        - Uses ONLY provided facts and contexts
        - No hallucinated or inferred information
        - Facts appear under relevant outline points
        - Matches maintain their original context

        3. Information Coverage (20 points)
        - High importance facts (8-10) are included
        - Critical decisions and actions covered
        - Essential context is preserved
        - No important information is missing

        4. Format Requirements (10 points)
        - Length is between 150-200 words
        - Professional tone maintained
        - Clear and concise writing
        - Logical flow between points

        Scoring Deductions:
        - Missing outline point with available facts (-10)
        - Wrong information placement (-8)
        - Hallucinated content (-15)
        - Missing high-importance fact (-10)
        - Incorrect context usage (-8)
        - Outside word limit (-10)

        Output: JSON with:
        - confidence_score (0-100)
        - feedback (specific issues and suggestions)
        """
        
        user_prompt = f"""
        Evaluate this summary against outline and requirements:

        Outline to Follow:
        {outline}

        Available Facts and Contexts:
        {summary_input['matched_information']}

        Unmatched Features:
        {summary_input['unmatched_features']}

        Generated Summary:
        {generated_summary}

        Check for:
        1. Outline adherence
        2. Fact accuracy
        3. Important information coverage
        4. Word limit (150-200)

        Provide detailed feedback on any issues found.
        """

        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(
            self.client, message, self.model, "Sumamry Checker Agent", category="Sumamry Checker Agent", 
            log_base_path=self.log_base_path,
            max_tokens=4000
        )

        enriched_template = _clean_response(response)

        try:
            parsed_template = json.loads(enriched_template)
        except json.JSONDecodeError:
            try:
                parsed_template = ast.literal_eval(enriched_template)
            except (ValueError, SyntaxError):
                logging.error(f"Error parsing checker response: {enriched_template}")
                return output_format
        
        return parsed_template

    def process_chunk_with_feedback(self, agent_id: str, summary_input: Dict, outline: List[str]) -> Tuple[str, float, str]:
        """Process with feedback loops for improvement."""
        feedback_prompt = ""
        best_summary = ""
        best_score = 0
        
        for attempt in range(3):
            summary = self.expert_agent(summary_input, outline, feedback_prompt)
            check_result = self.checker_agent(summary_input, outline, summary)
            
            if check_result["confidence_score"] > best_score:
                best_summary = summary
                best_score = check_result["confidence_score"]
            
            if check_result["confidence_score"] >= 80:
                break
            
            logging.info(f"Revising summary for {agent_id} due to low confidence score: {check_result['confidence_score']}")
            feedback_prompt = f"Feedback for improvement: {_normalise_feedback(check_result['feedback'])}"
        
        return best_summary, best_score, feedback_prompt


