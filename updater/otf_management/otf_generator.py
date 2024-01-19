

import logging
import os
from pathlib import Path
from jinja2 import FileSystemLoader, Environment
from codecs import unicode_escape_decode

from orchestrator_utils.logger.logger import init_logger


class OTFGenerator(object):
    """
    OTF Generator class which generate the OTF for the specific template.
    """
    def __init__(self, path, out_path, otf_apply_parameter = "hdr, meta, standard_metadata") -> None:
        self.logger = init_logger(self.__class__.__name__, logging.INFO)
        self.path = path
        self.infile = "tenant_inc.p4.j2"
        self.outfile = os.path.splitext(self.infile)[0]
        self.out_path = out_path
        self.otf_path = "include/tenant_otfs/"
        self.otfs_by_code = {}
        self.template = None
        self.vxlan_field = "hdr.vxlan.vni"
        self.otf_apply_parameter = otf_apply_parameter

        if self.otf_path[-1] != "/":
            self.otf_path += "/"
        if self.path[-1] != "/":
            self.path += "/"
        if not os.path.exists(self.path + self.otf_path):
            os.makedirs(self.path + self.otf_path)

    def _update_in_network_tenant_controller(self):
        """
        Build the code for the in-network tenant controller. 
        """
        vnis = [otf["vnis"] for tdc_name, otf in self.otfs_by_code.items()]
        main_ingress = [otf["mainIngress"] for tdc_name, otf in self.otfs_by_code.items()]
        tenant_func_ids = [otf["tenant_func_id_num"] for tdc_name, otf in self.otfs_by_code.items()]
        
        format_string = "if (hdr.vxlan.isValid()) {{ \n\t\t\t {} \n\t\t\t }}\n".format(self._generate_otf_switch_clause(vnis, tenant_func_ids, main_ingress))
        self.logger.debug(format_string)
        return format_string

    def _save_p4code_to_file(self, tenant_cnf_id, p4code : str):
        """
        Save the OTF p4code to file.

        Parameters:
        -----------
        tenant_cnf_id : str
            Unique tenant cnf identifier for the deployment to be checked.
        p4code : str
            The OTF P4Code as string representation
        """
        try:
            self.logger.info("Save p4 code from {} to {}".format(tenant_cnf_id, "./" + self.path + self.otf_path + tenant_cnf_id + ".p4"))
            with open("./" + self.path + self.otf_path + tenant_cnf_id + ".p4", "w") as f:
                if p4code.find("\\") != -1:
                    p4code, _ = unicode_escape_decode(p4code)
                f.write(p4code)
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)
    
    def _remove_otf_p4code(self, tenant_cnf_id):
        """
        Remove OTF code file
        """
        os.remove("./" + self.path + self.otf_path + tenant_cnf_id + ".p4")

    def _generate_otf_include_statements(self):
        """
        Generate the OTF include statements.
        """
        include_string = ""
        for otf in self.otfs_by_code.keys():
            include_string += "#include \"{}{}.p4\"\n".format(self.otf_path, otf)
            
        return include_string


    def _generate_otf_switch_clause(self, vnis, tenant_func_id_num, main_ingress):
        """
        Generate OTF switch clause for the in-network tenant controller.

        Parameters:
        -----------
        tenant_func_id_num : int
            Unique number for this OTF
        vnis : str | int | list
            VNIs which should be checked in the condition.
        main_ingress : str
            Name of the OTF main ingress
        """
        assert len(vnis) == len(main_ingress)
        otf_switch_clause = ""
        if len(vnis) == 1:
            if isinstance(vnis, list) and isinstance(main_ingress, list):
                otf_switch_clause = " if {} {{ \n\t\t\t\t meta.tenant_meta.tenant_func_id = {}; \n\t\t\t\t {}.apply({}); \n\t\t\t\t }} \n".format(self._generate_vnis_switch_condition_clause(vnis[0]), tenant_func_id_num[0], main_ingress[0], self.otf_apply_parameter)
            elif isinstance(vnis, (str, int)) and isinstance(main_ingress, (str)):
                otf_switch_clause = " if {} {{ \n\t\t\t\t meta.tenant_meta.tenant_func_id = {}; \n\t\t\t\t {}.apply({}) \n\t\t\t\t }} \n".format(self._generate_vnis_switch_condition_clause(vnis), tenant_func_id_num, main_ingress, self.otf_apply_parameter)
            else:
                raise TypeError("Unsupported type for ...")
        else:
            for i in range(len(vnis)):
                if i == 0:
                    otf_switch_clause += "\t if {} {{ \n\t\t\t\t\t meta.tenant_meta.tenant_func_id = {}; \n\t\t\t\t\t {}.apply({}); \n\t\t\t\t }} ".format(self._generate_vnis_switch_condition_clause(vnis[i]), tenant_func_id_num[i], main_ingress[i], self.otf_apply_parameter)
                else:
                    otf_switch_clause += " else if {} {{ \n\t\t\t\t\t meta.tenant_meta.tenant_func_id = {}; \n\t\t\t\t\t {}.apply({}); \n\t\t\t\t }} ".format(self._generate_vnis_switch_condition_clause(vnis[i]), tenant_func_id_num[i], main_ingress[i], self.otf_apply_parameter)
        return otf_switch_clause
    
    def _generate_vnis_switch_condition_clause(self, vnis):
        """
        Helper method for generating vnis switch condition clause.

        Parameters:
        -----------
        vnis : str | int | list
            VNIs which should be checked in the condition.
        """
        if isinstance(vnis, (str, int)):
            vni_str = "({} == {})".format(self.vxlan_field, vnis)
        else:
            vni_str = "("
            for vni in vnis:
                vni_str += self.vxlan_field + " == " + str(vni) + " || "
            vni_str = vni_str[:-4]
            vni_str += ")"
        self.logger.debug(vni_str)
        return vni_str
    
    def is_otf_in_generator(self, tenant_cnf_id):
        """
        Check if the given tenant_cnf_id is present in the otf_generator's otfs_by_code dictionary.

        Parameters:
        -----------
        tenant_cnf_id: str
            The tenant_cnf_id to check.

        Returns:
        --------
        bool: True if the tenant_cnf_id is present, False otherwise.
        """
        return tenant_cnf_id in self.otfs_by_code.keys()

    def add_otf_by_code(self, tenant_cnf_id, tenant_func_id_num, vnis, main_ingress, p4code):
        """
        Method to add OTF to a template.

        Parameters:
        -----------
        tenant_cnf_id : str
            Unique tenant cnf identifier for the deployment to be checked.
        tenant_func_id_num : int
            Unique number for this OTF
        vnis : str | int | list
            VNIs which should be checked in the condition.
        main_ingress : str
            Name of the OTF main ingress
        p4code : str
            The OTF P4Code as string representation.
        """
        if tenant_cnf_id in self.otfs_by_code.keys():
            raise KeyError("Key {} exists".format(tenant_cnf_id))
        else:
            self.otfs_by_code.update({tenant_cnf_id: {"vnis": vnis, "tenant_func_id_num": tenant_func_id_num, "mainIngress": main_ingress, "p4Code": p4code}})
            self._save_p4code_to_file(tenant_cnf_id, p4code)


    def update_otf_by_code(self, tenant_cnf_id, tenant_func_id_num, vnis, main_ingress, p4code):
        """
        Method to update existing OTF to a template.

        Parameters:
        -----------
        tenant_cnf_id : str
            Unique tenant cnf identifier for the deployment to be checked.
        tenant_func_id_num : int
            Unique number for this OTF
        vnis : str | int | list
            VNIs which should be checked in the condition.
        main_ingress : str
            Name of the OTF main ingress
        p4code : str
            The OTF P4Code as string representation.
        """
        if tenant_cnf_id in self.otfs_by_code.keys():
            self.otfs_by_code[tenant_cnf_id]["vnis"] = vnis
            self.otfs_by_code[tenant_cnf_id]["tenant_func_id_num"] = tenant_func_id_num
            self.otfs_by_code[tenant_cnf_id]["mainIngress"] = main_ingress
            self.otfs_by_code[tenant_cnf_id]["p4Code"] = p4code
            self._save_p4code_to_file(tenant_cnf_id, p4code)
        else:
            raise KeyError("{} does not exist".format(tenant_cnf_id))

    def delete_otf(self, tenant_cnf_id):
        """
        Method to delete OTF from a template.

        Parameters:
        -----------
        tenant_cnf_id : str
            Unique tenant cnf identifier for the deployment to be checked.
        """
        if tenant_cnf_id in self.otfs_by_code.keys():
            self.otfs_by_code.pop(tenant_cnf_id)
            self._remove_otf_p4code(tenant_cnf_id)
        else:
            raise KeyError("{} does not exist".format(tenant_cnf_id))

    def generate(self):
        """
        Generate P4 Code from TIF Template.
        """
        try:
            if self.template is None:
                env = Environment(loader=FileSystemLoader(Path(self.path)))
                self.template = env.get_template(self.infile)
            in_network_tenant_controller_logic = self._update_in_network_tenant_controller()
            otf_includes = self._generate_otf_include_statements()
            outputText = self.template.render(in_network_tenant_controller_logic = in_network_tenant_controller_logic, otf_includes = otf_includes)  # this is where to put args to the template renderer
            with open(self.out_path + self.outfile, 'w') as f:
                f.write(outputText)
            self.logger.debug(outputText)
        except Exception as ex:
            self.logger.exception(ex, exc_info=True)