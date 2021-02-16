import glocaltokens.utils.token as token_utils


class TypeTestMixin:
    def assertIsString(self, variable):
        self.assertTrue(
            type(variable) == str, msg=f"Given variable {variable} is not String type"
        )

    def assertIsAASET(self, variable):
        self.assertTrue(
            type(variable) == str and token_utils.is_aas_et(variable),
            msg=f"Given variable {variable} doesn't follow the AAS_ET format",
        )
