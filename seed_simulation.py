import random
import uuid
from db_manager import (
    add_church, add_campaign, register_respondent, 
    save_responses, reset_db_force
)
from survey_config import SURVEY_QUESTIONS

def generate_comment(area_title, score):
    positives = ["Excelente trabajo en esta área.", "Se nota el compromiso del equipo.", "La visión es clara y nos guía bien.", "Estamos creciendo mucho aquí."]
    neutrals = ["Hay margen de mejora.", "Se están haciendo esfuerzos pero falta constancia.", "Necesitamos más recursos en esta parte.", "A veces no queda claro el proceso."]
    negatives = ["Hay mucha confusión en este punto.", "No veo que estemos avanzando.", "Falta mucha comunicación del liderazgo.", "Es un área crítica que requiere atención inmediata."]
    
    if score >= 8:
        return random.choice(positives) + f" (Ref: {area_title})"
    elif score >= 5:
        return random.choice(neutrals) + f" (Ref: {area_title})"
    else:
        return random.choice(negatives) + f" (Ref: {area_title})"

def seed_data():
    print("Iniciando carga de datos de prueba...")
    
    # Reset DB if needed? User didn't ask for a reset this time, 
    # but since it's a "test" maybe it's better to keep it clean.
    # Actually, better just to ADD the new church.
    
    church_name = "Puerta Celestial"
    church_id = add_church(church_name, "Ubicación de Prueba", "puerta777")
    
    token = "zion-pres" # Requested link in history was this, let's use it or unique one
    campaign_id = add_campaign(church_id, token, "Híbrido", "2026-12-31")
    
    respondents = [
        {"name": "Pedro Picapiedra", "user": "pedro.p", "pass": "pedro123", "role": "Pastor", "gender": "Masculino", "age": "> 50", "mins": "Educación, Caballeros y Familia", "score_range": (5, 10)},
        {"name": "Vilma Picapiedra", "user": "vilma.p", "pass": "vilma123", "role": "Pastor", "gender": "Femenino", "age": "31-50", "mins": "Familia, Damas y Celulas", "score_range": (5, 10)},
        {"name": "Betty Marmol", "user": "betty.m", "pass": "betty123", "role": "Líder", "gender": "Femenino", "age": "31-50", "mins": "Damas, Celulas y Niños", "score_range": (2, 7)},
        {"name": "Pablo Marmol", "user": "pablo.m", "pass": "pablo123", "role": "Líder", "gender": "Masculino", "age": "31-50", "mins": "Caballeros, Alabanza y Familia", "score_range": (2, 7)},
        {"name": "Bam Bam Marmol", "user": "bambam.m", "pass": "bambam123", "role": "Líder", "gender": "Masculino", "age": "18-30", "mins": "Jovenes, Alabanza", "score_range": (2, 7)},
        {"name": "Peebles Picapiedra", "user": "peebles.p", "pass": "peebles123", "role": "Líder", "gender": "Femenino", "age": "18-30", "mins": "Jovenes, Alabanza, Celulas", "score_range": (2, 7)},
    ]
    
    results_summary = []
    
    for r in respondents:
        # Register
        resp_id = register_respondent(
            church_id, r["user"], r["pass"], 
            r["name"], "555-0100", r["gender"], r["age"], r["role"], r["mins"]
        )
        
        if resp_id:
            responses = []
            for area_id, area_info in SURVEY_QUESTIONS.items():
                for q_idx in range(len(area_info["questions"])):
                    score = random.randint(r["score_range"][0], r["score_range"][1])
                    comment = generate_comment(area_info["title"], score)
                    responses.append((area_id, q_idx + 1, score, comment))
            
            save_responses(resp_id, responses)
            results_summary.append((r["name"], r["user"], r["pass"]))
            print(f"Cargado: {r['name']}")
        else:
            print(f"Error o usuario duplicado: {r['user']}")

    print("\n--- Credenciales de Prueba ---")
    print("| Nombre | Usuario | Password |")
    print("|--------|---------|----------|")
    for row in results_summary:
        print(f"| {row[0]} | {row[1]} | {row[2]} |")

if __name__ == "__main__":
    seed_data()
