import re
import ast
import sympy
import sympy.abc
from sympy.parsing import sympy_parser, sympy_tokenize
from sympy.core.numbers import Integer, Float, Rational
from sympy.core.basic import Basic


__all__ = ["UnsafeInputException", "cleanup_string", "is_valid_symbol", "parse_expr"]


# What constitutes a relation?
RELATIONS_REGEX = '(.*?)(==|<=|>=|<|>)(.*)'

# We need to be able to sanitise Unicode user input. Whitelist allowed characters:
ALLOWED_CHARACTER_LIST = ["\x20",            # space
                          "\x28-\x29",       # left and right brackets
                          "\x2A-\x2F",       # times, plus, comma, minus, decimal point, divide
                          "\x30-\x39",       # numbers 0-9
                          "\x3C-\x3E",       # less than, equal, greater than
                          "\x41-\x5A",       # uppercase letters A-Z
                          "\x5E-\x5F",       # caret symbol, underscore
                          "\x61-\x7A",       # lowercase letters a-z
                          u"\u00B1",         # plus or minus symbol
                          u"\u00B2-\u00B3",  # squared and cubed notation
                          u"\u00BC-\u00BE",  # quarter, half, three quarters
                          u"\u00D7",         # unicode times sign
                          u"\u00F7"]         # unicode division sign

# Join these into a regular expression that matches everything except allowed characters:
UNSAFE_CHARACTERS_REGEX = r"[^" + "".join(ALLOWED_CHARACTER_LIST) + r"]+"
# Symbols may only contain 0-9, A-Z, a-z and underscores:
NON_SYMBOL_REGEX = r"[^\x30-\x39\x41-\x5A\x61-\x7A\x5F]+"


#####
# Parsing Cleanup
#####

class UnsafeInputException(ValueError):
    """An exception to be raised when unexpected input is provided."""
    pass


def cleanup_string(string, reject_unsafe_input):
    """Some simple sanity checking and cleanup to perform on passed in strings.

       Since arbitrary strings are passed in, and 'eval' is used implicitly by
       sympy; try and remove the worst offending things from strings.
    """
    # Flask gives us unicode objects anyway, the command line might not!
    if not isinstance(string, unicode):
        string = unicode(string.decode('utf-8'))  # We'll hope it's UTF-8
    # Replace all non-whitelisted characters in the input:
    string = re.sub(UNSAFE_CHARACTERS_REGEX, '?', string)
    if reject_unsafe_input:
        # If we have non-whitelisted charcaters, raise an exception:
        if "?" in string:
            # We replaced all non-whitelisted characters with '?' (and '?' is not whitelisted)
            # so if any '?' characters exist the string must have contained bad input.
            raise UnsafeInputException("Unexpected input characters provided!")
    else:
        # otherwise just swap the blacklisted characters for spaces and proceed.
        string = string.replace("?", " ")
    # Further cleanup, because some allowed characters are only allowed in certain circumstances:
    string = re.sub(r'([^0-9])\.([^0-9])|(.?)\.([^0-9])|([^0-9])\.(.?)', '\g<1> \g<2>', string)  # Allow the . character only surrounded by numbers
    string = string.replace("lambda", "lamda").replace("Lambda", "Lamda")  # We can't override the built-in keyword
    string = string.replace("__", " ")  # We don't need double underscores, exploits do
    string = re.sub(r'(?<![=<>])=(?![=<>])', '==', string)  # Replace all single equals signs with double equals
    # Replace Unicode equivalents:
    string = string.replace(u"\u00B2", "**2").replace(u"\u00B3", "**3")
    string = string.replace(u"\u00BC", "(1/4)").replace(u"\u00BD", "(1/2)").replace(u"\u00BE", "(3/4)")
    string = string.replace(u"\u00D7", "*").replace(u"\u00F7", "/")
    return string


def is_valid_symbol(string):
    """Test whether a string can be a valid symbol.

       Useful for filtering out functions and operators.
    """
    if re.search(NON_SYMBOL_REGEX, string) is not None:
        return False
    return True


#####
# Custom Symbol / Function / Operator Classes:
#####

class Equal(sympy.Equality):
    """A custom class to override sympy.Equality's str method."""
    def __str__(self):
        """Print the equation in a nice way!"""
        return "%s == %s" % (self.lhs, self.rhs)


def factorial(n):
    """Stop sympy blindly calculating factorials no matter how large.

       If 'n' is a number of some description, ensure that it is smaller than
       a cutoff, otherwise sympy will simply evaluate it, no matter how long that
       may take to complete!
       - 'n' should be a sympy object, that sympy.factorial(...) can use.
    """
    if isinstance(n, (Integer, Float, Rational)) and n > 50:
        raise ValueError("[Factorial]: Too large integer to compute factorial effectively!")
    else:
        return sympy.factorial(n)


#####
# Custom SymPy Parser Transformations:
#####

def _auto_symbol(tokens, local_dict, global_dict):
    """Replace the sympy builtin auto_symbol with a much more aggressive version.

       We have to replace this, because SymPy attempts to be too accepting of
       what it considers to be valid input and allows Pythonic behaviour.
       We only really want pure mathematics notations where possible!"""
    result = []
    # As with all tranformations, we have to iterate through the tokens and
    # return the modified list of tokens:
    for tok in tokens:
        tokNum, tokVal = tok
        if tokNum == sympy_tokenize.NAME:
            name = tokVal
            # Check if the token name is in the local/global dictionaries.
            # If it is, convert it correctly, otherwise leave untouched.
            if name in local_dict:
                result.append((sympy_tokenize.NAME, name))
                continue
            elif name in global_dict:
                obj = global_dict[name]
                if isinstance(obj, (Basic, type)) or callable(obj):
                    # If it's a function/basic class, don't convert it to a Symbol!
                    result.append((sympy_tokenize.NAME, name))
                    continue
            result.extend([
                (sympy_tokenize.NAME, 'Symbol'),
                (sympy_tokenize.OP, '('),
                (sympy_tokenize.NAME, repr(str(name))),
                (sympy_tokenize.OP, ')'),
            ])
        else:
            result.append((tokNum, tokVal))

    return result


#####
# Customised SymPy Internals:
#####

def _evaluateFalse(s):
    """Replaces operators with the SymPy equivalents and set evaluate=False.

       Unlike the built-in evaluateFalse(...), we want to use a slightly more
       sophisticated EvaluateFalseTransformer and make operators AND functions
       evaluate=False.
        - 's' should be a string of Python code for the maths abstract syntax tree.
    """
    node = ast.parse(s)
    node = _EvaluateFalseTransformer().visit(node)
    # node is a Module, we want an Expression
    node = ast.Expression(node.body[0].value)

    return ast.fix_missing_locations(node)


class _EvaluateFalseTransformer(sympy_parser.EvaluateFalseTransformer):
    """Extend default SymPy EvaluateFalseTransformer to affect functions too.

       The SymPy version does not force function calls to be 'evaluate=False',
       which means expressions like "log(x, 10)" get simplified to "log(x)/log(10)"
       or "cos(-x)" becomes "cos(x)". For our purposes, this is unhelpful and so
       we also prevent this from occuring.

       Currently there is a list of functions not to transform, because some do
       not support the "evaluate=False" argument. This isn't particularly nice or
       future proof!
    """
    def visit_Call(self, node):
        # Since we have overridden the visit method, we are now responsible for
        # ensuring all child nodes are visited too. This is done most simply by
        # calling generic_visit(...) on ourself:
        self.generic_visit(node)
        # FIXME: Some functions cannot accept "evaluate=False" as an argument
        # without their __new__() method raising a TypeError. There is probably
        # some underlying reason which we could take into account of.
        # For now, blacklist those known to be problematic:
        _ignore_functions = ["Integer", "Float", "Symbol", "factorial", "sqrt", "Sqrt"]
        if node.func.id in _ignore_functions:
            # print "\tIgnoring function: %s" % node.func.id
            pass
        else:
            # print "\tModifying function: %s" % node.func.id
            node.keywords.append(ast.keyword(arg='evaluate', value=ast.Name(id='False', ctx=ast.Load())))
        # We must return the node, modified or not:
        return node


#####
# Custom Parsers:
#####

# These constants are needed to address some security issues.
# We don't want to use the default transformations, and we need to use a
# whitelist of functions the parser should allow to match.
_TRANSFORMS = (sympy.parsing.sympy_parser.auto_number, _auto_symbol,
               sympy.parsing.sympy_parser.convert_xor, sympy_parser.split_symbols,
               sympy_parser.implicit_multiplication, sympy_parser.function_exponentiation)

_GLOBAL_DICT = {"Symbol": sympy.Symbol, "Integer": sympy.Integer, "Float": sympy.Float, "Rational": sympy.Rational,
                "Mul": sympy.Mul, "Pow": sympy.Pow, "Add": sympy.Add,
                "iI": sympy.I, "piPI": sympy.pi, "eE": sympy.E,
                "Rel": sympy.Rel, "Eq": Equal,
                "Derivative": sympy.Derivative, "diff": sympy.Derivative,
                "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
                "Sin": sympy.sin, "Cos": sympy.cos, "Tan": sympy.tan,
                "arcsin": sympy.asin, "arccos": sympy.acos, "arctan": sympy.atan,
                "ArcSin": sympy.asin, "ArcCos": sympy.acos, "ArcTan": sympy.atan,
                "sinh": sympy.sinh, "cosh": sympy.cosh, "tanh": sympy.tanh,
                "arcsinh": sympy.asinh, "arccosh": sympy.acosh, "arctanh": sympy.atanh,
                "cosec": sympy.csc, "sec": sympy.sec, "cot": sympy.cot,
                "Csc": sympy.csc, "Sec": sympy.sec, "Cot": sympy.cot,
                "arccosec": sympy.acsc, "arcsec": sympy.asec, "arccot": sympy.acot,
                "ArcCsc": sympy.acsc, "ArcSec": sympy.asec, "ArcCot": sympy.acot,
                "cosech": sympy.csch, "sech": sympy.sech, "coth": sympy.coth,
                "exp": sympy.exp, "log": sympy.log, "ln": sympy.ln,
                "Exp": sympy.exp, "Log": sympy.log, "Ln": sympy.ln,
                # "factorial": factorial,  "Factorial": factorial,
                "sqrt": sympy.sqrt, "abs": sympy.Abs,
                "Sqrt": sympy.sqrt, "Abs": sympy.Abs}


def _replace_relations(match_object):
    """To ensure that relations like >, >= or == are not evaluated, swap them with Rel class.

       Function to take in a regular expression match from RELATIONS_REGEX and
       replace the string with an actual Relation class from sympy. This is required
       to stop sympy from immediately evaluating all inequalities. It's recursive,
       which should allow nested inequalities - but this functionality may be removed.
        - 'match_object' should be a regex match object matching RELATIONS_REGEX.
    """
    lhs = match_object.group(1).strip()
    relation = match_object.group(2)
    rhs = match_object.group(3).strip()
    if (relation == "=="):
        # Override the default equality relation to use a custom (human-readable) one.
        return "Eq(%s,%s)" % (lhs, rhs)
    else:
        return "Rel(%s,%s,'%s')" % (lhs, rhs, relation)


def parse_expr(expression_str, transformations=_TRANSFORMS, local_dict=None, global_dict=_GLOBAL_DICT):
    """A clone of sympy.sympy_parser.parse_expr(...) which prevents all evaluation.

       Arbitrary untrusted input should be cleaned using "cleanup_string" before
       calling this method.
       This is almost a direct copy of the SymPy code, but it also converts inline
       relations like "==" or ">=" to the Relation class to prevent evaluation
       and uses a more aggresive set of transformations and better prevents any
       evaluation.
    """
    if local_dict is None:
        local_dict = {}
    expression_str = re.sub(RELATIONS_REGEX, _replace_relations, expression_str)  # To ensure not evaluated, swap relations with Rel class
    code = sympy_parser.stringify_expr(expression_str, local_dict, global_dict, transformations)
    ef_code = _evaluateFalse(code)
    code_compiled = compile(ef_code, '<string>', 'eval')
    return sympy_parser.eval_expr(code_compiled, local_dict, global_dict)