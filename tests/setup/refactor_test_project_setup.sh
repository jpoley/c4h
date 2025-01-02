#!/bin/bash

# Create test_project directory structure if it doesn't exist
mkdir -p test_project/data_prep
mkdir -p test_project/data_out
mkdir -p test_project/f1
mkdir -p test_project/f2
mkdir -p test_project/f3
mkdir -p test_project/f4

# Create Python scripts for each step

# Step 1: Count Rows
echo """
import csv

def count_rows(file_path):
    with open(file_path, mode='r') as file:
        csv_reader = csv.reader(file)
        row_count = sum(1 for row in csv_reader) - 1  # Exclude header
    print(f\"[Stage 1] Number of rows in {file_path}: {row_count}\")
    return row_count

if __name__ == \"__main__\":
    count_rows('data/stage1_input.csv')
""" > test_project/f1/step_01.py

# Step 2: Validate Schema
echo """
import csv

def validate_schema(file_path, expected_columns):
    with open(file_path, mode='r') as file:
        csv_reader = csv.reader(file)
        header = next(csv_reader)
        is_valid = header == expected_columns
        print(f\"[Stage 2] Schema validation for {file_path}: {'Passed' if is_valid else 'Failed'}\")
    return is_valid

if __name__ == \"__main__\":
    validate_schema('data/stage2_input.csv', ['ID', 'Name', 'Age'])
""" > test_project/f2/step_02.py

# Step 3: Join Files
echo """
import csv

def join_files(file1_path, file2_path, key_index1, key_index2, output_file):
    with open(file1_path, mode='r') as file1, open(file2_path, mode='r') as file2:
        reader1 = csv.reader(file1)
        reader2 = csv.reader(file2)
        
        header1 = next(reader1)
        header2 = next(reader2)
        
        joined_rows = []
        for row1 in reader1:
            for row2 in reader2:
                if row1[key_index1] == row2[key_index2]:
                    joined_rows.append(row1 + row2)
        
        with open(output_file, mode='w', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(header1 + header2)
            writer.writerows(joined_rows)
    
    print(f\"[Stage 3] Joined files {file1_path} and {file2_path} into {output_file}\")

if __name__ == \"__main__\":
    join_files('data/stage3_input1.csv', 'data/stage3_input2.csv', 0, 0, 'data/stage3_output.csv')
""" > test_project/f3/step_03.py

# Step 4: Filter Rows
echo """
import csv

def filter_rows(file_path, output_file, condition):
    with open(file_path, mode='r') as file:
        csv_reader = csv.reader(file)
        header = next(csv_reader)
        filtered_rows = [row for row in csv_reader if condition(row)]
        
    with open(output_file, mode='w', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(filtered_rows)
    
    print(f\"[Stage 4] Filtered rows from {file_path} to {output_file}\")

if __name__ == \"__main__\":
    filter_rows('data/stage4_input.csv', 'data/stage4_output.csv', lambda row: int(row[2]) > 18)
""" > test_project/f4/step_04.py

# Create main.py

echo """
import os
import sys

# Importing step functions from each module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'f1')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'f2')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'f3')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'f4')))

from step_01 import count_rows
from step_02 import validate_schema
from step_03 import join_files
from step_04 import filter_rows

def main():
    # Define paths
    input_folder = 'test_project/data_prep'
    output_folder = 'test_project/data_out'
    
    # Ensure output folder exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Step 1: Count Rows
    input_file_1 = os.path.join(input_folder, 'stage1_input.csv')
    output_file_1 = os.path.join(output_folder, 'stage1_output.txt')
    row_count = count_rows(input_file_1)
    with open(output_file_1, 'w') as f:
        f.write(f\"Number of rows: {row_count}\\n\")

    # Step 2: Validate Schema
    input_file_2 = os.path.join(input_folder, 'stage2_input.csv')
    output_file_2 = os.path.join(output_folder, 'stage2_output.txt')
    is_valid = validate_schema(input_file_2, ['ID', 'Name', 'Age'])
    with open(output_file_2, 'w') as f:
        f.write(f\"Schema validation: {'Passed' if is_valid else 'Failed'}\\n\")

    # Step 3: Join Files
    input_file_3_1 = os.path.join(input_folder, 'stage3_input1.csv')
    input_file_3_2 = os.path.join(input_folder, 'stage3_input2.csv')
    output_file_3 = os.path.join(output_folder, 'stage3_output.csv')
    join_files(input_file_3_1, input_file_3_2, 0, 0, output_file_3)

    # Step 4: Filter Rows
    input_file_4 = output_file_3  # Use output from Step 3 as input for Step 4
    output_file_4 = os.path.join(output_folder, 'stage4_output.csv')
    filter_rows(input_file_4, output_file_4, lambda row: int(row[2]) > 18)

if __name__ == \"__main__\":
    main()
""" > test_project/main.py

# Create CSV files

# Stage 1 Input CSV
echo "ID,Name,Age,Gender,Location,Occupation" > test_project/data_prep/stage1_input.csv
echo "1,Alice,25,F,New York,Engineer" >> test_project/data_prep/stage1_input.csv
echo "2,Bob,30,M,San Francisco,Designer" >> test_project/data_prep/stage1_input.csv
echo "3,Charlie,22,M,Los Angeles,Teacher" >> test_project/data_prep/stage1_input.csv
echo "4,Diana,28,F,Chicago,Doctor" >> test_project/data_prep/stage1_input.csv
echo "5,Edward,35,M,Seattle,Manager" >> test_project/data_prep/stage1_input.csv
echo "6,Fiona,26,F,Miami,Engineer" >> test_project/data_prep/stage1_input.csv
echo "7,George,33,M,Boston,Architect" >> test_project/data_prep/stage1_input.csv
echo "8,Hannah,29,F,Dallas,Lawyer" >> test_project/data_prep/stage1_input.csv
echo "9,Ian,31,M,Austin,Scientist" >> test_project/data_prep/stage1_input.csv
echo "10,Julia,27,F,Denver,Accountant" >> test_project/data_prep/stage1_input.csv

# Stage 2 Input CSV
echo "ID,Name,Age" > test_project/data_prep/stage2_input.csv
echo "1,Alice,25" >> test_project/data_prep/stage2_input.csv
echo "2,Bob,30" >> test_project/data_prep/stage2_input.csv
echo "3,Charlie,22" >> test_project/data_prep/stage2_input.csv
echo "4,Diana,28" >> test_project/data_prep/stage2_input.csv
echo "5,Edward,35" >> test_project/data_prep/stage2_input.csv
echo "6,Fiona,26" >> test_project/data_prep/stage2_input.csv
echo "7,George,33" >> test_project/data_prep/stage2_input.csv
echo "8,Hannah,29" >> test_project/data_prep/stage2_input.csv
echo "9,Ian,31" >> test_project/data_prep/stage2_input.csv
echo "10,Julia,27" >> test_project/data_prep/stage2_input.csv

# Stage 3 Input 1 CSV
echo "ID,Department,Salary" > test_project/data_prep/stage3_input1.csv
echo "1,Engineering,70000" >> test_project/data_prep/stage3_input1.csv
echo "2,Design,80000" >> test_project/data_prep/stage3_input1.csv
echo "3,Education,50000" >> test_project/data_prep/stage3_input1.csv
echo "4,Healthcare,90000" >> test_project/data_prep/stage3_input1.csv
echo "5,Management,95000" >> test_project/data_prep/stage3_input1.csv
echo "6,Engineering,72000" >> test_project/data_prep/stage3_input1.csv
echo "7,Architecture,88000" >> test_project/data_prep/stage3_input1.csv
echo "8,Legal,91000" >> test_project/data_prep/stage3_input1.csv
echo "9,Research,94000" >> test_project/data_prep/stage3_input1.csv
echo "10,Finance,68000" >> test_project/data_prep/stage3_input1.csv

# Stage 3 Input 2 CSV
echo "ID,Office,Experience" > test_project/data_prep/stage3_input2.csv
echo "1,New York,3" >> test_project/data_prep/stage3_input2.csv
echo "2,San Francisco,5" >> test_project/data_prep/stage3_input2.csv
echo "3,Los Angeles,2" >> test_project/data_prep/stage3_input2.csv
echo "4,Chicago,6" >> test_project/data_prep/stage3_input2.csv
echo "5,Seattle,8" >> test_project/data_prep/stage3_input2.csv
echo "6,Miami,4" >> test_project/data_prep/stage3_input2.csv
echo "7,Boston,7" >> test_project/data_prep/stage3_input2.csv
echo "8,Dallas,5" >> test_project/data_prep/stage3_input2.csv
echo "9,Austin,9" >> test_project/data_prep/stage3_input2.csv
echo "10,Denver,4" >> test_project/data_prep/stage3_input2.csv

# Stage 4 Input CSV
echo "ID,Name,Age,Gender,Location,Occupation" > test_project/data_prep/stage4_input.csv
echo "1,Alice,25,F,New York,Engineer" >> test_project/data_prep/stage4_input.csv
echo "2,Bob,30,M,San Francisco,Designer" >> test_project/data_prep/stage4_input.csv
echo "3,Charlie,22,M,Los Angeles,Teacher" >> test_project/data_prep/stage4_input.csv
echo "4,Diana,28,F,Chicago,Doctor" >> test_project/data_prep/stage4_input.csv
echo "5,Edward,35,M,Seattle,Manager" >> test_project/data_prep/stage4_input.csv
echo "6,Fiona,26,F,Miami,Engineer" >> test_project/data_prep/stage4_input.csv
echo "7,George,33,M,Boston,Architect" >> test_project/data_prep/stage4_input.csv
echo "8,Hannah,29,F,Dallas,Lawyer" >> test_project/data_prep/stage4_input.csv
echo "9,Ian,31,M,Austin,Scientist" >> test_project/data_prep/stage4_input.csv
echo "10,Julia,27,F,Denver,Accountant" >> test_project/data_prep/stage4_input.csv

