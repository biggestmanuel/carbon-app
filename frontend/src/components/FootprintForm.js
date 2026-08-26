import React, { useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "../config";

function FootprintForm({ token }) {
  const [carKm, setCarKm] = useState(0);
  const [electricity, setElectricity] = useState(0);
  const [meatMeals, setMeatMeals] = useState(0);
  const [plantMeals, setPlantMeals] = useState(0);

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.post(
        `${API_BASE_URL}/footprint/calculate`,
        {
          car_km: parseFloat(carKm),
          electricity_kwh: parseFloat(electricity),
          meat_meals: parseInt(meatMeals),
          plant_meals: parseInt(plantMeals),
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      alert(`Your footprint is ${res.data.total} kg CO₂`);
    } catch (err) {
      console.error(err);
      const msg = err.response?.data?.msg || "Error calculating footprint. Check backend connection.";
      alert(msg);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="number"
        placeholder="Car km"
        value={carKm}
        onChange={(e) => setCarKm(e.target.value)}
      />
      <input
        type="number"
        placeholder="Electricity kWh"
        value={electricity}
        onChange={(e) => setElectricity(e.target.value)}
      />
      <input
        type="number"
        placeholder="Meat meals"
        value={meatMeals}
        onChange={(e) => setMeatMeals(e.target.value)}
      />
      <input
        type="number"
        placeholder="Plant meals"
        value={plantMeals}
        onChange={(e) => setPlantMeals(e.target.value)}
      />
      <button type="submit">Calculate</button>
    </form>
  );
}

export default FootprintForm;
