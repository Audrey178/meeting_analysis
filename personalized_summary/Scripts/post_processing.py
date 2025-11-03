from model_handler import ModelHandler

class PostProcessor:
    def __init__(self, client, model="gpt-4-turbo"):
        self.client = client
        self.model = model

    def post_process_summary(self, combined_summary):
        system_prompt = f"""
        You are an expert editor tasked with refining a document summary. Your goal is to create a polished final summary between 100-150 words that flows naturally and maintains a coherent narrative throughout.

        CRITICAL REFINEMENT GUIDELINES:
        1. FOCUS ON NARRATIVE FLOW:
           - Create smooth, logical transitions between different points
           - Establish clear relationships between facts
           - Connect ideas with appropriate discourse markers
           - Ensure each sentence builds naturally on the previous one
           - Avoid abrupt jumps between topics

        2. MAINTAIN TOPICAL COHERENCE:
           - Group related information together
           - Follow a logical progression of ideas
           - Create a narrative thread that binds the content
           - Use topic sentences to introduce new conceptual areas
           - Ensure proper context for each point

        3. CONCISENESS AND LENGTH:
           - Aim for exactly 100-150 words total
           - Prioritize the most important information
           - Eliminate redundancies and repetitive elements
           - Remove unnecessary qualifiers and wordiness
           - Preserve key details while condensing expression

        4. STYLE AND CLARITY:
           - Use consistent tense and perspective
           - Maintain a professional, objective tone
           - Ensure precision and clarity in expression
           - Remove any introductory phrases like "The summary is..."
           - Create a cohesive document that reads as a single, unified piece

        OUTPUT GUIDELINES:
        - Present as 1-2 well-structured paragraphs
        - Provide exactly 100-150 words (strict requirement)
        - Ensure the summary reads as a coherent whole
        - Maintain factual accuracy from the original content
        - Focus on creating a smooth, natural reading experience

        WHAT TO AVOID:
        - Abrupt transitions between topics
        - Disconnected factual statements without logical flow
        - Introducing new information not in the original
        - Excessive detail on one topic at the expense of others
        - Uneven or inconsistent coverage of the material
        """

        user_prompt = f"""
        Here is a document summary that needs refinement:

        {combined_summary}

        Please create a polished final summary that:
        1. Maintains all the key information
        2. Flows naturally with smooth transitions
        3. Presents a coherent narrative
        4. Contains exactly 100-150 words
        5. Reads as a single, unified piece

        Focus especially on improving the narrative flow and eliminating any "jumpiness" between different points.
        """

        message = ModelHandler.build_message(system_prompt, user_prompt)


        refined_summary = ModelHandler.call_model_with_retry(
            self.client, message, self.model, "regeneration",    
            category="summary_refinement", 
            log_base_path="./atomic-facts/data_store/cost_time_logging/",
            verbose=True, max_tokens=4000
        )
        print(refined_summary)
        return refined_summary