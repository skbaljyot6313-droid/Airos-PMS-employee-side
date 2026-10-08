/** Pure session gate — AiROS Staff is restricted to employee-role users
 *  backed by an employee record (role 'employee' + employee_uid). */
export const isEmployeeSession = (
  u: { role: string; employee_uid: string | null } | null | undefined
): boolean => !!u && u.role === 'employee' && !!u.employee_uid;

export const EMPLOYEE_GATE_MESSAGE =
  'Access denied: AiROS Staff is restricted to operations employees.';
