rd_reg_as_hex = 0x03 
rd_output_coil_as_hex = 0x01
rd_direct_input_as_hex = 0x02

slave_id = 0x00

# global for access by both setup and update
rd_reg_cnt = 1              # number of input registers used
rd_output_coil_cnt = 2      # number of output coils used
rd_direct_input_cnt = 4       # number of direct inputs

rd_output_coil_address = 0
rd_direct_input_address = rd_output_coil_address+rd_output_coil_cnt + 1
rd_reg_address = rd_direct_input_address+rd_direct_input_cnt+1
