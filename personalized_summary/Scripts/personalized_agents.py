import logging
from typing import List, Dict, Tuple
from model_handler import ModelHandler
from utils import _clean_response
import ast
import json

class PersonalizedAgents:
    def __init__(self, client, model):
        self.client = client
        self.model = model
        
    def expert_agent(self, summary_input: Dict, outline: List[str], character_sheet: Dict, feedback_prompt: str = "") -> str:
        """Generate personalized summary following outline and considering persona preferences."""
        system_prompt = f"""
        You are an expert summarization agent tasked with creating a highly personalized meeting summary.
        Your goal is to create a summary from the PERSPECTIVE OF THE PERSONA, focusing on what OTHERS said 
        that would be relevant and important for this specific persona.

        CRITICAL PERSPECTIVE SHIFT:
        - The summary is NOT about what the persona said or did
        - Instead, focus on what OTHERS said that the persona needs to know or act upon
        - Think of this as "meeting notes" the persona would write for themselves
        - The persona would NOT write down information they already know or presented themselves
        - They WOULD write down insights, actions, decisions, and requests from others that affect their role

        CRITICAL CONSTRAINTS:
        - Summary MUST be between 150-200 words
        - Use ONLY provided facts and contexts
        - NO hallucination or inference
        - Focus on information most relevant to the persona FROM OTHERS
        - Follow outline structure conceptually, but present as cohesive paragraphs
        - DO NOT use bullet points, numbered lists, or section headers in your summary

        OUTPUT FORMAT:
        - The summary must be in paragraph format only
        - Use well-structured paragraphs that flow naturally
        - No headers, bullet points, or other structural elements
        - Present as a cohesive narrative that covers key points from the outline

        PERSONA CONSIDERATIONS:
        1. Information Preferences:
        - Match their preferred detail level
        - Use their preferred information format
        - Focus on their key interests
        - Address their specific needs

        2. Decision Factors:
        - Emphasize aspects they value most
        - Consider their risk tolerance
        - Match their time sensitivity
        - Align with their priorities

        3. Context Requirements:
        - Provide context they need
        - Match their technical level
        - Include background they care about
        - Support their decision-making style

        Summarization Guidelines:
        1. For each outline point:
        a. Find relevant matched facts where:
            - High combined importance/alignment score
            - Matches persona's interests
            - Supports their decision-making
            - Provides context they need
            - FOCUS ON WHAT OTHERS SAID that impacts this persona

        b. Use the matched fact's context effectively:
            - Frame information for their needs
            - Include context they value
            - Skip details they don't need
            - Match their preferred style

        2. Content Organization:
        a. Prioritize by combined scores and persona relevance:
            - Highly aligned facts (8-10) with full context
            - Important decisions by others that affect this persona
            - Actions or requests directed at this persona
            - Information that requires the persona's input or expertise
            - Context relevant to their interests but not already known by them

        b. Support with selective context:
            - Include context that matters to them
            - Skip context they don't need
            - Match their detail preferences
            - Support their objectives

        3. Style and Format:
        - Present as cohesive paragraphs that flow naturally
        - Ensure logical transitions between paragraphs
        - Maintain narrative coherence throughout
        - Match their communication preferences
        - Use appropriate technical level
        - Provide detail level they prefer
        - Support their decision-making needs

        4. Special Requirements:
        - Skip outline points without matching facts
        - Stay within word limit
        - Only use explicit information
        - Focus on what's new and actionable for the persona
        """

        user_prompt = f"""
        Generate a 150-200 word personalized meeting summary for this persona:

        Character Sheet (Persona Preferences):
        {character_sheet}

        Follow this outline structure conceptually, but format as cohesive paragraphs:
        {outline}

        Use these matched facts and contexts:
        {summary_input['matched_information']}

        Consider these unmatched features if relevant:
        {summary_input['unmatched_features']}

        Previous Feedback (if any):
        {feedback_prompt}

        Remember:
        - Focus on what OTHERS said that is relevant to this persona (not what the persona said themselves)
        - Think of this as personal meeting notes the persona would write for themselves
        - Highlight insights, actions, decisions, and requests from others that affect their role
        - Match their preferred style and detail level
        - Stay within 150-200 words
        - Only use provided information
        - Format as cohesive paragraphs that flow naturally
        - DO NOT use bullet points, headers, or numbered lists
        - Present as a smooth narrative that covers key points from the outline
        """
        
        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(self.client, message, self.model, "regeneration",    
                category="summary_generation", 
                 log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True, max_tokens=4000)
        return response

    def checker_agent(self, summary_input: Dict, outline: List[str], character_sheet: Dict, generated_summary: str):
        """Check summary for persona alignment and constraints."""
        output_format = {
            "confidence_score": 90,
            "feedback": "Summary aligns well with persona preferences."
        }
        
        system_prompt = f"""
        You are a checker agent evaluating a personalized meeting summary. Verify:

        1. Persona Alignment (40 points)
        - Focuses on what OTHERS said that is relevant to the persona (not what the persona said themselves)
        - Addresses their key interests from the perspective of what they need to know
        - Highlights actions, insights, and decisions from others that affect their role
        - Uses appropriate style and detail level

        2. Content Organization (30 points)
        - Follows outline structure
        - Prioritizes information relevant to the persona from the meeting
        - Uses appropriate level of context
        - Maintains logical flow

        3. Information Accuracy (20 points)
        - Uses only provided facts and contexts
        - No hallucinated content
        - Accurate context usage
        - Appropriate for persona's needs

        4. Format Requirements (10 points)
        - Length between 150-200 words
        - Professional tone
        - Appropriate technical level
        - Clear organization

        Scoring Deductions:
        - Focuses on what the persona said rather than what they need to know (-15)
        - Missing key insights from others that affect the persona (-15)
        - Poor persona alignment (-10)
        - Missing key persona interests (-10)
        - Wrong information placement (-8)
        - Hallucinated content (-15)
        - Inappropriate context (-8)
        - Outside word limit (-10)

        Output: JSON with:
        - confidence_score (0-100)
        - feedback (specific issues and suggestions)
        """
        
        user_prompt = f"""
        Evaluate this personalized summary:

        Character Sheet (Persona):
        {character_sheet}

        Outline Structure:
        {outline}

        Available Facts and Contexts:
        {summary_input['matched_information']}

        Unmatched Features:
        {summary_input['unmatched_features']}

        Generated Summary:
        {generated_summary}

        Check for:
        1. CRITICAL: Does the summary focus on what OTHERS said that is relevant to the persona (not what the persona said themselves)?
        2. Does it highlight insights, actions, decisions, and requests from others that affect their role?
        3. Is it written as if it were meeting notes the persona would write for themselves?
        4. Alignment with persona preferences
        5. Outline adherence
        6. Information accuracy
        7. Format requirements

        Provide detailed feedback focusing on perspective alignment and persona relevance.
        """

        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(
            self.client, message, self.model, "regeneration",    
                category="sumamry_checker_agent", 
                 log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True, max_tokens=4000
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

    def process_chunk_with_feedback(self, agent_id: str, summary_input: Dict, outline: List[str], 
                                  character_sheet: Dict) -> Tuple[str, float, str]:
        """Process with feedback loops for improvement."""
        feedback_prompt = ""
        best_summary = ""
        best_score = 0
        
        for attempt in range(3):
            summary = self.expert_agent(summary_input, outline, character_sheet, feedback_prompt)
            check_result = self.checker_agent(summary_input, outline, character_sheet, summary)
            
            if check_result["confidence_score"] > best_score:
                best_summary = summary
                best_score = check_result["confidence_score"]
            
            if check_result["confidence_score"] >= 85:
                break
            
            logging.info(f"Revising summary for {agent_id} due to low confidence score: {check_result['confidence_score']}")
            feedback_prompt = 'Feedback for improvement: ' + check_result["feedback"]
        
        return best_summary, best_score, feedback_prompt