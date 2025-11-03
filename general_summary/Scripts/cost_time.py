import os

def parse_category_file(file_path):
    """
    Parse the category log file to extract tokens, cost, and time.
    """
    input_tokens = 0
    output_tokens = 0
    cost = 0
    duration = 0
    
    with open(file_path, 'r') as file:
        lines = file.readlines()
        
        for line in lines:
            if line.startswith("Input Tokens:"):
                input_tokens += int(line.split(":")[1].strip())
            elif line.startswith("Output Tokens:"):
                output_tokens += int(line.split(":")[1].strip())
            elif line.startswith("Cost - Input Tokens:"):
                cost += float(line.split(":")[1].strip().split(",")[0].strip().replace("$", ""))
            elif line.startswith("Duration:"):
                duration += float(line.split(":")[1].strip().split()[0])
    
    return input_tokens, output_tokens, cost, duration

def accumulate_category_data(log_folder_path):
    """
    Accumulate data from all category log files and calculate totals.
    """
    category_data = {}
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0
    total_duration = 0

    # Get all category files from the folder
    category_files = [f for f in os.listdir(log_folder_path) if f.endswith('_logs.txt')]
    
    # Parse each category file and accumulate totals
    for category_file in category_files:
        category_name = category_file.replace('_logs.txt', '')  # Remove '_logs.txt' to get the category name
        category_file_path = os.path.join(log_folder_path, category_file)
        
        input_tokens, output_tokens, cost, duration = parse_category_file(category_file_path)
        
        # If the category already exists, accumulate its values; otherwise, initialize them
        if category_name not in category_data:
            category_data[category_name] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0,
                "duration": 0
            }
        
        category_data[category_name]["input_tokens"] += input_tokens
        category_data[category_name]["output_tokens"] += output_tokens
        category_data[category_name]["cost"] += cost
        category_data[category_name]["duration"] += duration
        
        # Accumulate grand totals
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_cost += cost
        total_duration += duration
    
    return total_input_tokens, total_output_tokens, total_cost, total_duration, category_data

def write_final_summary(output_file_path, total_input_tokens, total_output_tokens, total_cost, total_duration, category_data):
    """
    Write the final summary to a text file, including category-wise totals.
    """
    with open(output_file_path, 'w') as summary_file:
        summary_file.write(f"Final Summary:\n\n")
        
        # Write category-wise totals
        for category, data in category_data.items():
            summary_file.write(f"Category: {category}\n")
            summary_file.write(f"  Total Input Tokens: {data['input_tokens']}\n")
            summary_file.write(f"  Total Output Tokens: {data['output_tokens']}\n")
            summary_file.write(f"  Total Cost: ${data['cost']:.4f}\n")
            summary_file.write(f"  Total Time: {data['duration']:.2f} seconds\n\n")
        
        # Write the final total summary
        summary_file.write(f"Total Input Tokens (all categories): {total_input_tokens}\n")
        summary_file.write(f"Total Output Tokens (all categories): {total_output_tokens}\n")
        summary_file.write(f"Total Cost (all categories): ${total_cost:.4f}\n")
        summary_file.write(f"Total Time (all categories): {total_duration:.2f} seconds\n")
