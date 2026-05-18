# Production placeholder: run this in a privileged Linux/Mininet environment.
def build_topology():
    return {'hosts':['teacher_terminal','student_terminal','guest_terminal','meeting_server','lab_server'], 'switches':['s1','s2'], 'links':7}
if __name__=='__main__': print(build_topology())
